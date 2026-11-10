"""scripts/steps/spec-capture.py: /spec's Design & Evidence Capture Routine (persist one design or evidence item).

Every test runs the real script in a temp project with no network and no dependence on the runner's home. The
resolver it calls is the repository's own scripts/resolve-spec-artifacts.py. The cases pin the lessons the command
text used to carry as prose: the id is the resolver's de-prefixed id, the first item creates both folders, a name
never leaves its folder, a prior artifact is never overwritten, and an unreadable source is a visible failure, not
a silent drop.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "spec-capture.py"
RESOLVER = REPO / "scripts" / "resolve-spec-artifacts.py"
SPEC_REL = "docs/dev/specs/spec-20261109-101010.md"
SPEC_ID = "20261109-101010"


def project(tmp_path: Path, spec_rel: str = SPEC_REL) -> Path:
    spec = tmp_path / spec_rel
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec: toy\n\n## Section 5: User's Acceptance Criterion\n\nadd validation\n", encoding="utf-8")
    return tmp_path


def run(cwd: Path, *args: str, stdin: bytes = b"", env: dict | None = None):
    full_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    full_env.update({"HOME": str(cwd.parent), **(env or {})})
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=full_env, input=stdin,
                          capture_output=True)
    facts = {}
    for line in proc.stdout.decode("utf-8").splitlines():
        key, sep, value = line.partition("=")
        assert sep and re.fullmatch(r"[a-z_]+", key), f"stdout carries a line that is not key=value: {line!r}"
        facts[key] = value
    return facts, proc


def design(cwd: Path, text: bytes, slug: str = "type check placement", turn: int = 3, spec: str = SPEC_REL, **kw):
    return run(cwd, "design", "--spec", spec, "--turn", str(turn), "--slug", slug, stdin=text, **kw)


def evidence(cwd: Path, source: Path | str, spec: str = SPEC_REL, **kw):
    return run(cwd, "evidence", "--spec", spec, "--from", str(source), **kw)


def folder(cwd: Path) -> Path:
    return cwd / "docs" / "dev" / "specs" / SPEC_ID


# ------------------------------------------------------------------ the id and the folders
def test_the_id_is_the_resolvers_de_prefixed_stem_and_both_folders_appear_with_the_first_item(tmp_path):
    cwd = project(tmp_path)
    facts, proc = design(cwd, b"put the check first\n")
    assert proc.returncode == 0, proc.stderr
    assert facts["spec_dir_id"] == SPEC_ID
    assert facts["bound_root"] == str(folder(cwd).resolve())
    assert (folder(cwd) / "design").is_dir() and (folder(cwd) / "evidence").is_dir()


def test_exactly_one_leading_spec_prefix_is_stripped(tmp_path):
    cwd = project(tmp_path, "docs/dev/specs/spec-spec-x.md")
    facts, _ = design(cwd, b"d\n", spec="docs/dev/specs/spec-spec-x.md")
    assert facts["spec_dir_id"] == "spec-x"
    assert (cwd / "docs/dev/specs/spec-x/design").is_dir()


def test_the_folders_are_not_split_artifacts_so_the_resolver_still_sees_no_split(tmp_path):
    cwd = project(tmp_path)
    design(cwd, b"d\n")
    evidence(cwd, cwd / SPEC_REL)
    out = subprocess.run([sys.executable, str(RESOLVER), "--spec-path", SPEC_REL, "--project-dir", str(cwd)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout)["views_available"] is False


def test_the_project_is_claude_project_dir_then_the_git_top_level(tmp_path):
    cwd = project(tmp_path / "proj")
    subprocess.run(["git", "init", "-q", str(cwd)], check=True)
    sub = cwd / "docs" / "dev"
    facts, proc = design(sub, b"d\n", spec=str(cwd / SPEC_REL))
    assert facts["artifact"] == f"docs/dev/specs/{SPEC_ID}/design/turn-3-type-check-placement.md", proc.stderr
    assert (folder(cwd) / "design" / "turn-3-type-check-placement.md").is_file()

    other = project(tmp_path / "other")
    facts, _ = design(sub, b"d\n", spec=str(other / SPEC_REL), env={"CLAUDE_PROJECT_DIR": str(other)})
    assert facts["bound_root"] == str(folder(other).resolve())


# ------------------------------------------------------------------ design
def test_a_pasted_design_is_written_verbatim_under_turn_n_and_the_slug(tmp_path):
    cwd = project(tmp_path)
    text = "Design: check types first.\n\n    indented line\n\ttabbed line\n日本語 and 中文 stay as typed\n"
    facts, proc = design(cwd, text.encode("utf-8"), slug="Type-check placement", turn=4)
    assert proc.returncode == 0 and facts["status"] == "persisted"
    assert facts["artifact"] == f"docs/dev/specs/{SPEC_ID}/design/turn-4-type-check-placement.md"
    assert (cwd / facts["artifact"]).read_bytes() == text.encode("utf-8")


def test_a_design_file_is_copied_byte_for_byte_with_no_transcoding(tmp_path):
    cwd = project(tmp_path)
    source = tmp_path / "runbook.md"
    payload = b"\xef\xbb\xbfrunbook\r\nline two \xff\xfe not utf-8\r\n"
    source.write_bytes(payload)
    facts, _ = run(cwd, "design", "--spec", SPEC_REL, "--turn", "2", "--slug", "runbook", "--from", str(source))
    assert facts["status"] == "persisted"
    assert (cwd / facts["artifact"]).read_bytes() == payload


def test_the_slug_is_sanitized_and_can_never_climb_out_of_the_design_folder(tmp_path):
    cwd = project(tmp_path)
    for slug, expected in (("../../etc/passwd", "etc-passwd"), ("A  B/C\\D", "a-b-c-d"), ("  !!  ", "design"),
                           ("x" * 200, "x" * 50), ("部署 layout", "部署-layout")):
        facts, proc = design(cwd, b"d\n" + slug.encode("utf-8"), slug=slug)
        assert proc.returncode == 0, proc.stderr
        assert facts["artifact"] == f"docs/dev/specs/{SPEC_ID}/design/turn-3-{expected}.md", slug
        assert (cwd / facts["artifact"]).resolve().parent == (folder(cwd) / "design").resolve()


def test_a_second_design_with_the_same_name_never_overwrites_the_first(tmp_path):
    cwd = project(tmp_path)
    first, _ = design(cwd, b"first\n")
    second, _ = design(cwd, b"second\n")
    digest = hashlib.sha256(b"second\n").hexdigest()[:8]
    assert first["artifact"].endswith("turn-3-type-check-placement.md")
    assert second["artifact"].endswith(f"turn-3-type-check-placement-{digest}.md")
    assert (cwd / first["artifact"]).read_bytes() == b"first\n"
    assert (cwd / second["artifact"]).read_bytes() == b"second\n"
    again, _ = design(cwd, b"second\n")
    assert again["artifact"] == second["artifact"]            # identical content is reused, not duplicated
    assert sorted(p.name for p in (folder(cwd) / "design").iterdir()) == sorted(
        [Path(first["artifact"]).name, Path(second["artifact"]).name])


# ------------------------------------------------------------------ evidence
def test_evidence_is_copied_under_its_own_name_and_a_taken_name_gets_a_content_hash(tmp_path):
    cwd = project(tmp_path)
    photo = tmp_path / "shots" / "photo.png"
    photo.parent.mkdir()
    photo.write_bytes(b"\x89PNG one")
    first, _ = evidence(cwd, photo)
    assert first["status"] == "persisted"
    assert first["artifact"] == f"docs/dev/specs/{SPEC_ID}/evidence/photo.png"

    other = tmp_path / "other" / "photo.png"
    other.parent.mkdir()
    other.write_bytes(b"\x89PNG two")
    second, _ = evidence(cwd, other)
    digest = hashlib.sha256(b"\x89PNG two").hexdigest()[:8]
    assert second["artifact"] == f"docs/dev/specs/{SPEC_ID}/evidence/photo-{digest}.png"
    assert (cwd / first["artifact"]).read_bytes() == b"\x89PNG one"
    assert (cwd / second["artifact"]).read_bytes() == b"\x89PNG two"


def test_an_evidence_name_with_odd_characters_is_made_safe_and_stays_in_its_folder(tmp_path):
    cwd = project(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    for raw, expected in (("my photo\x01.png", "my_photo_.png"), ("a..b.png", "a.b.png"), (".env", "env"),
                          ("screen shot (1).PNG", "screen_shot__1_.PNG"), ("日志.log", "日志.log")):
        path = src / raw
        path.write_bytes(raw.encode("utf-8"))
        facts, proc = evidence(cwd, path)
        assert proc.returncode == 0 and facts["status"] == "persisted", (raw, proc.stderr)
        assert facts["artifact"] == f"docs/dev/specs/{SPEC_ID}/evidence/{expected}", raw
        assert (cwd / facts["artifact"]).resolve().parent == (folder(cwd) / "evidence").resolve()


def test_only_the_basename_of_the_source_is_used(tmp_path):
    cwd = project(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "log.txt").write_text("x", encoding="utf-8")
    facts, _ = evidence(cwd, nested / ".." / "b" / "log.txt")
    assert facts["artifact"] == f"docs/dev/specs/{SPEC_ID}/evidence/log.txt"


# ------------------------------------------------------------------ failures are visible
def test_an_unreadable_source_is_a_failed_fact_with_exit_zero_and_nothing_archived(tmp_path):
    cwd = project(tmp_path)
    for source in (tmp_path / "missing.png", tmp_path):
        facts, proc = evidence(cwd, source)
        assert proc.returncode == 0
        assert facts["status"] == "failed" and facts["error"], facts
        assert "artifact" not in facts
    facts, proc = run(cwd, "design", "--spec", SPEC_REL, "--turn", "1", "--slug", "runbook", "--from",
                      str(tmp_path / "missing.md"))
    assert proc.returncode == 0 and facts["status"] == "failed" and "artifact" not in facts
    assert list((folder(cwd) / "design").iterdir()) == [] and list((folder(cwd) / "evidence").iterdir()) == []


def test_an_unreadable_spec_exits_one_without_creating_folders(tmp_path):
    facts, proc = design(tmp_path, b"d\n", spec="docs/dev/specs/spec-none.md")
    assert proc.returncode == 1 and facts == {}
    assert not (tmp_path / "docs").exists()


def test_wrong_arguments_exit_two(tmp_path):
    cwd = project(tmp_path)
    for args in (("design", "--spec", SPEC_REL, "--slug", "x"), ("design", "--spec", SPEC_REL, "--turn", "3"),
                 ("design", "--spec", SPEC_REL, "--turn", "0", "--slug", "x"), ("evidence", "--spec", SPEC_REL),
                 ("persist", "--spec", SPEC_REL)):
        _, proc = run(cwd, *args)
        assert proc.returncode == 2, args
