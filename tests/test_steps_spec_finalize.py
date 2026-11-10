"""scripts/steps/spec-finalize.py: /spec Step 6's two mechanical calls (`prepare`, `complete`).

Every test runs the real script in a temp project with no network and no dependence on the runner's home. The
Section 9 cases pin what the command text used to spell as regex prose: the three limitation-line shapes are
records, not paths; every other listed design or evidence path must exist under the spec's own per-id folder.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "spec-finalize.py"
SPEC_ID = "20261109-101010"
SPEC_REL = f"docs/dev/specs/spec-{SPEC_ID}.md"
HEAD = ("# Spec: toy\n\n## Section 5: User's Acceptance Criterion\n\nadd validation\n\n---\n\n"
        "## Section 9: Design & Evidence References\n\n<!-- WHAT: reference lines -->\n\n### 9.1: Design References\n\n"
        "<!-- consumers: [all] -->\n")
DESIGN = f"docs/dev/specs/{SPEC_ID}/design/turn-3-type-check.md"
EVIDENCE = f"docs/dev/specs/{SPEC_ID}/evidence/photo.png"


def make(tmp_path: Path, nine: str = "_Not yet populated._\n", tail: str = "", files: tuple = ()) -> Path:
    spec = tmp_path / SPEC_REL
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(HEAD + nine + tail, encoding="utf-8")
    for rel in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    return tmp_path


def run(cwd: Path, action: str, script: Path = SCRIPT, spec: str = SPEC_REL, env: dict | None = None,
        extra: tuple = ()):
    full_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    full_env.update({"HOME": str(cwd.parent), **(env or {})})
    proc = subprocess.run([sys.executable, str(script), action, "--spec", spec, *extra], cwd=cwd, env=full_env,
                          capture_output=True, text=True)
    facts: dict[str, list] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep and re.fullmatch(r"[a-z_]+", key), f"stdout carries a line that is not key=value: {line!r}"
        facts.setdefault(key, []).append(value)
    return facts, proc


def one(facts: dict, key: str) -> str:
    assert len(facts[key]) == 1, facts
    return facts[key][0]


# ------------------------------------------------------------------ prepare: the id and the line count
def test_prepare_prints_the_resolvers_id_and_the_newline_count_wc_prints(tmp_path):
    cwd = make(tmp_path)
    facts, proc = run(cwd, "prepare")
    assert proc.returncode == 0, proc.stderr
    wc = subprocess.run(["wc", "-l"], stdin=(cwd / SPEC_REL).open("rb"), capture_output=True, text=True).stdout
    assert one(facts, "spec_id") == SPEC_ID
    assert one(facts, "monolith_lines") == wc.strip()
    assert (one(facts, "references"), one(facts, "status")) == ("0", "ok") and "dangling" not in facts


def test_a_final_line_without_a_newline_is_not_counted(tmp_path):
    cwd = make(tmp_path, nine="_Not yet populated._")
    facts, _ = run(cwd, "prepare")
    text = (cwd / SPEC_REL).read_bytes()
    assert one(facts, "monolith_lines") == str(text.count(b"\n")) and not text.endswith(b"\n")


def test_a_spec_with_no_section_9_has_nothing_to_check(tmp_path):
    spec = tmp_path / SPEC_REL
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec\n\n## Section 5\n\nreq\n", encoding="utf-8")
    facts, _ = run(tmp_path, "prepare")
    assert (one(facts, "references"), one(facts, "status")) == ("0", "ok")


# ------------------------------------------------------------------ prepare: the Section 9 guard
def test_listed_references_that_exist_pass(tmp_path):
    nine = f"- `{DESIGN}` — where the check goes\n\n### 9.2: Evidence References\n\n<!-- consumers: [all] -->\n- `{EVIDENCE}` — shot\n"
    cwd = make(tmp_path, nine, files=(DESIGN, EVIDENCE))
    facts, _ = run(cwd, "prepare")
    assert (one(facts, "references"), one(facts, "status")) == ("2", "ok") and "dangling" not in facts


def test_a_missing_reference_is_dangling_and_every_one_is_named(tmp_path):
    nine = f"- `{DESIGN}` — here\n- `{EVIDENCE}` — gone\n- `{DESIGN}` — listed twice\n"
    cwd = make(tmp_path, nine, files=(DESIGN,))
    facts, proc = run(cwd, "prepare")
    assert proc.returncode == 0                       # a fact for the command to act on, not an exit
    assert facts["dangling"] == [EVIDENCE] and one(facts, "status") == "dangling"
    assert one(facts, "references") == "2"            # distinct paths


def test_the_three_limitation_shapes_are_records_not_paths(tmp_path):
    nine = ("- (inline) pasted screenshot — provided inline (no filesystem path in this harness); durable archival needs a file path\n"
            f"- (unpersisted design) /srv/notes/runbook.md — read/copy failed: No such file; not archived `{DESIGN}`\n"
            f"- (unpersisted) /tmp/shot.png — copy failed: Permission denied; not archived `{EVIDENCE}`\n")
    cwd = make(tmp_path, nine)
    facts, _ = run(cwd, "prepare")
    assert (one(facts, "references"), one(facts, "status")) == ("0", "ok") and "dangling" not in facts


def test_the_sentinel_needs_whitespace_after_the_closing_paren(tmp_path):
    # the guard reads `\s` after the paren (a `\b` there never matches the emitted `) `): a paren glued to the
    # next character is not a limitation record, so its path is checked
    nine = f"- (inline)`{DESIGN}` — not a limitation record\n"
    cwd = make(tmp_path, nine)
    facts, _ = run(cwd, "prepare")
    assert facts["dangling"] == [DESIGN]


def test_a_dangling_reference_converted_to_a_limitation_line_carrying_its_path_passes(tmp_path):
    nine = f"- `{EVIDENCE}` — shot\n- (unpersisted) {EVIDENCE} — copy failed: file vanished; not archived\n"
    cwd = make(tmp_path, nine)
    facts, _ = run(cwd, "prepare")
    assert (one(facts, "references"), one(facts, "status")) == ("1", "ok") and "dangling" not in facts


def test_a_path_under_another_specs_folder_or_climbing_out_is_dangling_even_when_the_file_exists(tmp_path):
    other = "docs/dev/specs/20250101-000000/design/turn-1-x.md"
    climb = f"docs/dev/specs/{SPEC_ID}/design/../../../../../secret.md"
    cwd = make(tmp_path, f"- `{other}` — theirs\n- `{climb}` — climbs\n", files=(other, "secret.md"))
    facts, _ = run(cwd, "prepare")
    assert facts["dangling"] == [other, climb] and one(facts, "status") == "dangling"


def test_paths_outside_section_9_are_not_checked(tmp_path):
    cwd = make(tmp_path, tail=f"\n## Section 10: later\n\n- `{DESIGN}` — mentioned elsewhere\n")
    facts, _ = run(cwd, "prepare")
    assert (one(facts, "references"), one(facts, "status")) == ("0", "ok")


def test_prepare_exits_one_for_an_unreadable_spec(tmp_path):
    facts, proc = run(tmp_path, "prepare", spec="docs/dev/specs/spec-none.md")
    assert proc.returncode == 1 and facts == {}


def test_prepare_follows_what_spec_capture_wrote(tmp_path):
    cwd = make(tmp_path, "_Not yet populated._\n")
    capture = REPO / "scripts" / "steps" / "spec-capture.py"
    done = subprocess.run([sys.executable, str(capture), "design", "--spec", SPEC_REL, "--turn", "3", "--slug",
                           "type check"], cwd=cwd, input=b"d\n", capture_output=True)
    artifact = next(l.split("=", 1)[1] for l in done.stdout.decode().splitlines() if l.startswith("artifact="))
    with (cwd / SPEC_REL).open("a", encoding="utf-8") as handle:
        handle.write(f"- `{artifact}` — the check\n")
    facts, _ = run(cwd, "prepare")
    assert (one(facts, "references"), one(facts, "status")) == ("1", "ok")


# ------------------------------------------------------------------ complete: the marker and the advisory lint
def split_folder(cwd: Path) -> Path:
    folder = cwd / "docs" / "dev" / "specs" / SPEC_ID
    (folder / "views").mkdir(parents=True)
    return folder


def test_complete_writes_the_marker_in_the_date_iseconds_form(tmp_path):
    cwd = make(tmp_path)
    folder = split_folder(cwd)
    facts, proc = run(cwd, "complete")
    assert proc.returncode == 0, proc.stderr
    marker = folder / ".split-complete"
    assert re.fullmatch(r"split-complete: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d\n", marker.read_text(encoding="utf-8"))
    assert one(facts, "marker") == f"docs/dev/specs/{SPEC_ID}/.split-complete" and one(facts, "spec_id") == SPEC_ID
    date = subprocess.run(["date", "-Iseconds"], capture_output=True, text=True).stdout.strip()
    assert re.sub(r"\d", "9", date) == re.sub(r"\d", "9", marker.read_text(encoding="utf-8").split(": ", 1)[1].strip())


def test_complete_refuses_to_write_a_marker_where_the_split_folder_does_not_exist(tmp_path):
    cwd = make(tmp_path)
    facts, proc = run(cwd, "complete")
    assert proc.returncode == 1 and facts == {} and "has not written the split" in proc.stderr
    assert not (cwd / "docs" / "dev" / "specs" / SPEC_ID).exists()


def test_the_repositorys_own_command_files_pass_the_lint(tmp_path):
    cwd = make(tmp_path)
    split_folder(cwd)
    facts, proc = run(cwd, "complete")
    assert one(facts, "lint") == "ok", proc.stderr


def harness(tmp_path: Path, commands: dict[str, str], lint: bool = True) -> Path:
    """A throwaway harness home: the script, the resolver, optionally the lint, and the given command files."""
    home = tmp_path / "harness"
    (home / "scripts" / "steps").mkdir(parents=True)
    (home / "commands").mkdir()
    shutil.copy(SCRIPT, home / "scripts" / "steps" / "spec-finalize.py")
    shutil.copy(REPO / "scripts" / "resolve-spec-artifacts.py", home / "scripts" / "resolve-spec-artifacts.py")
    if lint:
        shutil.copy(REPO / "scripts" / "lint-spec-id-centralization.py", home / "scripts" / "lint-spec-id-centralization.py")
    for name, text in commands.items():
        (home / "commands" / f"{name}.md").write_text(text, encoding="utf-8")
    return home


def test_a_command_that_derives_the_spec_id_inline_is_flagged_but_never_fails_finalize(tmp_path):
    home = harness(tmp_path, {"dev": 'SPEC_ID=$(basename "$SPEC_PATH" .md)\n', "spec": "clean\n"})
    cwd = make(tmp_path / "proj")
    split_folder(cwd)
    facts, proc = run(cwd, "complete", script=home / "scripts" / "steps" / "spec-finalize.py")
    assert proc.returncode == 0
    assert one(facts, "lint") == "flagged"
    assert "WARNING: centralization lint flagged inline spec-id derivation" in proc.stderr and "dev.md:1" in proc.stderr
    assert (cwd / "docs" / "dev" / "specs" / SPEC_ID / ".split-complete").is_file()


def test_missing_lint_or_command_files_are_skipped_not_errors(tmp_path):
    cwd = make(tmp_path / "proj")
    split_folder(cwd)
    no_lint = harness(tmp_path / "a", {"spec": "clean\n"}, lint=False)
    facts, proc = run(cwd, "complete", script=no_lint / "scripts" / "steps" / "spec-finalize.py")
    assert proc.returncode == 0 and one(facts, "lint") == "skipped"
    no_commands = harness(tmp_path / "b", {})
    facts, proc = run(cwd, "complete", script=no_commands / "scripts" / "steps" / "spec-finalize.py")
    assert proc.returncode == 0 and one(facts, "lint") == "skipped"


def test_the_project_dir_option_beats_the_environment(tmp_path):
    cwd = make(tmp_path / "proj")
    split_folder(cwd)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    facts, proc = run(elsewhere, "complete", spec=str(cwd / SPEC_REL), env={"CLAUDE_PROJECT_DIR": str(elsewhere)},
                      extra=("--project-dir", str(cwd)))
    assert proc.returncode == 0, proc.stderr
    assert (cwd / "docs" / "dev" / "specs" / SPEC_ID / ".split-complete").is_file() and one(facts, "spec_id") == SPEC_ID


def test_wrong_arguments_exit_two(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), "finish", "--spec", "x"], capture_output=True, text=True)
    assert proc.returncode == 2
    proc = subprocess.run([sys.executable, str(SCRIPT), "prepare"], capture_output=True, text=True)
    assert proc.returncode == 2


# ------------------------------------------------------------------ the command text calls what the scripts accept
COMMAND = REPO / "commands" / "spec.md"
BASH_SAFETY = REPO / "hooks" / "pretool-bash-safety.sh"
BINDINGS = (("<HARNESS_ROOT>", str(REPO)), ("<spec_path>", SPEC_REL), ("<N>", "3"), ("<short title>", "type check"),
            ("<the user's HOW-text, verbatim>", "the check goes first"))


def fences(text: str) -> list[tuple[str, str]]:
    """(language, body) of each fenced block, in order; an indented fence loses its indent."""
    out, lang, body = [], None, []
    for line in text.split("\n"):
        m = re.match(r"^\s*```(\w*)\s*$", line)
        if m and lang is None:
            lang, body = m.group(1), []
        elif m:
            out.append((lang, "\n".join(body) + "\n"))
            lang = None
        elif lang is not None:
            body.append(line.strip() if line.strip() in ("DESIGN_TEXT", "SPEC_TEXT") else line.lstrip())
    return out


def script_calls() -> list[str]:
    """Each fenced bash block of commands/spec.md that calls a scripts/steps/spec-*.py, placeholders filled."""
    out = []
    for lang, block in fences(COMMAND.read_text(encoding="utf-8")):
        if lang != "bash" or "scripts/steps/spec-" not in block:
            continue
        for key, value in BINDINGS:
            block = block.replace(key, value)
        out.append(block)
    return out


def test_the_command_calls_each_script_in_the_shapes_its_steps_use():
    calls = script_calls()
    firsts = [c.split("\n")[0] for c in calls]
    assert firsts[0].startswith(f'python3 "{REPO}/scripts/steps/spec-capture.py" design --spec {SPEC_REL} --turn 3 --slug "type check"')
    assert firsts[1] == f'python3 "{REPO}/scripts/steps/spec-finalize.py" prepare --spec {SPEC_REL}'
    assert firsts[2] == f'python3 "{REPO}/scripts/steps/spec-finalize.py" complete --spec {SPEC_REL}'
    assert len(calls) == 3


def test_the_command_text_calls_run_as_written(tmp_path):
    cwd = make(tmp_path)
    split_folder(cwd)
    capture, prepare, complete = script_calls()
    expected = {"capture": "status=persisted", "prepare": "status=ok", "complete": "lint="}
    for name, call in zip(expected, (capture, prepare, complete)):
        done = subprocess.run(["bash", "-c", call], cwd=cwd, capture_output=True, text=True,
                              env={**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)})
        assert done.returncode == 0, (name, done.stderr)
        assert expected[name] in done.stdout, (name, done.stdout)
    assert (cwd / "docs" / "dev" / "specs" / SPEC_ID / "design" / "turn-3-type-check.md").read_text() == "the check goes first\n"
    assert (cwd / "docs" / "dev" / "specs" / SPEC_ID / ".split-complete").is_file()


def test_bash_safety_accepts_every_script_call_the_command_makes(tmp_path):
    cwd = make(tmp_path)
    for call in script_calls():
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": call}, "cwd": str(cwd)})
        done = subprocess.run(["bash", str(BASH_SAFETY)], input=payload, text=True, capture_output=True, cwd=cwd,
                              env={**os.environ, "HOME": str(tmp_path), "CLAUDE_STATE_DIR": str(tmp_path / "state")})
        assert done.returncode == 0, (call, done.stderr)


def test_both_dispatch_templates_name_their_subagent_type_before_the_prompt():
    templates = [body for lang, body in fences(COMMAND.read_text(encoding="utf-8")) if "Use Agent tool with:" in body]
    types = [re.search(r'^\s*-\s*subagent_type:\s*"([\w-]+)"', body, re.M).group(1) for body in templates]
    assert types == ["spec", "qa"]
    assert all(body.index("subagent_type") < body.index("- prompt:") for body in templates)
    assert all(body.count("run_in_background: false") == 1 for body in templates)
