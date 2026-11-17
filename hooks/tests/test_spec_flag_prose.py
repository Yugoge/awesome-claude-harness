"""A1 (over-block audit): prompt-workflow.py took any `--spec` / `—spec` / `–spec`
in a /dev, /redev, /dev-command or /dev-overnight prompt as the --spec flag, and
the word after it as the spec path, so ordinary prose (`the API—spec section`,
`tests for --spec parsing`) was refused at UserPromptSubmit as an unresolved
spec (exit 2). The flag is now the first dash-spec whose next token is a spec
reference: shaped like a path (a `/` or `\\`, a leading `~` or `.`, a file
extension) or naming a file under the project. A real flag naming a missing
spec still refuses the prompt, whichever dash was typed.

Every prompt runs through the hook's real entry point with a throwaway HOME,
project and state dir (test_spec_path._submit)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spec_path import SID, _prompt_workflow, _spec_lines, _submit  # noqa: E402

PROSE = {
    "em_dash_prose": "align the docs with the API—spec section first",
    "en_dash_prose": "align the docs with the API–spec section first",
    "double_hyphen_prose": "add tests for --spec parsing",
    "double_hyphen_prose_sentence_end": "add tests for --spec parsing.",
}

# Real flags naming no readable spec: each must still refuse the prompt.
MISSING = {
    "bare_file": ("x --spec missing.md", "missing.md"),
    "relative_path": ("x --spec docs/dev/specs/missing.md", "docs/dev/specs/missing.md"),
    "em_dash_flag": ("x —spec missing.md", "missing.md"),
    "en_dash_flag": ("x –spec missing.md", "missing.md"),
    "glued_em_dash_path": ("x—spec missing.md", "missing.md"),
    "prose_then_flag": ("add tests for --spec parsing --spec missing.md", "missing.md"),
}


@pytest.mark.parametrize("command", ["dev", "redev", "dev-command"])
@pytest.mark.parametrize("case", sorted(PROSE))
def test_dash_spec_in_prose_does_not_refuse_the_prompt(tmp_path, command, case):
    proj, result = _submit(tmp_path, f"/{command} {PROSE[case]}")
    assert result.returncode == 0, result.stderr
    assert "(unresolved)" not in result.stderr
    assert _spec_lines(result.stdout) == ["Spec: none"]
    assert len(list((proj / ".claude" / "dev-registry").iterdir())) == 1


@pytest.mark.parametrize("case", sorted(PROSE))
def test_dash_spec_in_prose_does_not_refuse_dev_overnight(tmp_path, case):
    proj, result = _submit(tmp_path, f"/dev-overnight 23:59 {PROSE[case]}", git=True)
    assert result.returncode == 0, result.stderr
    assert "(unresolved)" not in result.stderr
    assert _spec_lines(result.stdout) == ["Spec: none"]
    state = json.loads((proj / ".claude" / f"overnight-state-{SID}.json").read_text())
    assert (state["spec_mode"], state["user_spec_path"]) == ("autonomous", None)


@pytest.mark.parametrize("command", ["dev", "redev", "dev-command"])
@pytest.mark.parametrize("case", sorted(MISSING))
def test_a_real_spec_flag_naming_a_missing_file_still_refuses(tmp_path, command, case):
    args, bad = MISSING[case]
    proj, result = _submit(tmp_path, f"/{command} {args}")
    assert result.returncode == 2
    assert f"Spec: {proj / bad} (unresolved)" in result.stderr.splitlines()
    assert result.stdout == ""
    assert not (proj / ".claude" / "dev-registry").exists()


@pytest.mark.parametrize("case", sorted(MISSING))
def test_a_real_spec_flag_naming_a_missing_file_still_refuses_dev_overnight(tmp_path, case):
    args, bad = MISSING[case]
    proj, result = _submit(tmp_path, f"/dev-overnight 23:59 {args}", git=True)
    assert result.returncode == 2
    assert f"Spec: {proj / bad} (unresolved)" in result.stderr.splitlines()
    assert not list((proj / ".claude").glob("overnight-state-*.json"))


@pytest.mark.parametrize("args", ["--spec myspec x", "—spec myspec x", "x for --spec myspec"])
def test_a_bare_name_of_an_existing_spec_is_the_flag(tmp_path, args):
    proj, result = _submit(tmp_path, f"/dev {args}", present=["myspec"])
    assert result.returncode == 0, result.stderr
    assert _spec_lines(result.stdout) == [f"Spec: {proj / 'myspec'} (explicit)"]


def test_strip_spec_arg_takes_the_first_reference_and_leaves_prose(tmp_path):
    pw = _prompt_workflow(tmp_path)
    assert pw._strip_spec_arg("add tests for --spec parsing") == ("add tests for --spec parsing", "")
    assert pw._strip_spec_arg("the API—spec section first") == ("the API—spec section first", "")
    assert pw._strip_spec_arg("fix --spec docs/s.md now") == ("fix now", "docs/s.md")
    assert pw._strip_spec_arg("about --spec parsing --spec ~/s.md") == ("about --spec parsing", "~/s.md")
    assert pw._strip_spec_arg("x –spec ./spec x") == ("x x", "./spec")


# --- A1 verifier round: a flag read as prose never swaps in another spec -------------------
# Each prompt below runs in a session that last wrote docs/dev/specs/foo.md. At 512cbcd these
# lost the flag and silently ran on foo.md; at d1abc798 each was refused.
SESSION_SPEC = "docs/dev/specs/foo.md"

# The <path> is wrapped or punctuated in the prompt, and the file exists: it is the spec.
WRAPPED_PRESENT = {
    "trailing_comma": "x --spec real.md, then go",
    "double_quoted": 'x --spec "real.md"',
    "backticked": "x --spec `real.md`",
}

# The <path> names nothing readable: the prompt is refused, naming the unwrapped path.
WRAPPED_MISSING = {
    "trailing_comma": ("x --spec missing.md, then go", "missing.md"),
    "single_quoted": ("x --spec 'missing.md'", "missing.md"),
    "quoted_with_space": ('x --spec "my spec.md"', "my spec.md"),
    "trailing_period": ("x --spec missing.md.", "missing.md"),
    "trailing_paren": ("x --spec missing.md)", "missing.md"),
    "parenthesized_flag": ("x (--spec missing.md)", "missing.md"),
    "angle_brackets": ("x --spec <missing.md>", "missing.md"),
    "directory": ("x --spec docs", "docs"),
    "leading_bare_name": ("--spec myspec x", "myspec"),
    "leading_bare_name_after_codex": ("--codex --spec myspec x", "myspec"),
}

COMMANDS = ["dev", "redev", "dev-command"]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("case", sorted(WRAPPED_PRESENT))
def test_a_wrapped_spec_path_resolves_to_that_spec(tmp_path, command, case):
    proj, result = _submit(tmp_path, f"/{command} {WRAPPED_PRESENT[case]}",
                           [SESSION_SPEC], [SESSION_SPEC, "real.md"])
    assert result.returncode == 0, result.stderr
    assert _spec_lines(result.stdout) == [f"Spec: {proj / 'real.md'} (explicit)"]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("case", sorted(WRAPPED_MISSING))
def test_a_wrapped_or_leading_flag_naming_no_readable_spec_refuses(tmp_path, command, case):
    args, bad = WRAPPED_MISSING[case]
    proj, result = _submit(tmp_path, f"/{command} {args}", [SESSION_SPEC], [SESSION_SPEC])
    assert result.returncode == 2, result.stdout
    assert f"Spec: {proj / bad} (unresolved)" in result.stderr.splitlines()
    assert result.stdout == ""
    assert not (proj / ".claude" / "dev-registry").exists()


@pytest.mark.parametrize("case", sorted(WRAPPED_PRESENT))
def test_a_wrapped_spec_path_resolves_for_dev_overnight(tmp_path, case):
    proj, result = _submit(tmp_path, f"/dev-overnight 23:59 {WRAPPED_PRESENT[case]}",
                           [SESSION_SPEC], [SESSION_SPEC, "real.md"], git=True)
    assert result.returncode == 0, result.stderr
    assert _spec_lines(result.stdout) == [f"Spec: {proj / 'real.md'} (explicit)"]
    state = json.loads((proj / ".claude" / f"overnight-state-{SID}.json").read_text())
    assert state["user_spec_path"] == str(proj / "real.md")


@pytest.mark.parametrize("case", sorted(WRAPPED_MISSING))
def test_a_wrapped_or_leading_flag_naming_no_readable_spec_refuses_dev_overnight(tmp_path, case):
    args, bad = WRAPPED_MISSING[case]
    proj, result = _submit(tmp_path, f"/dev-overnight 23:59 {args}", [SESSION_SPEC], [SESSION_SPEC],
                           git=True)
    assert result.returncode == 2, result.stdout
    assert f"Spec: {proj / bad} (unresolved)" in result.stderr.splitlines()
    assert not list((proj / ".claude").glob("overnight-state-*.json"))


# A bare word after a mid-text --spec is prose (`add tests for --spec parsing`), so the prompt
# runs; the run then gets no spec and a note, never the spec the session last wrote.
DROPPED = {
    "bare_name_last": ("x --spec myspec", "myspec"),
    "prose_word": ("add tests for --spec parsing", "parsing"),
    "prose_word_sentence_end": ("add tests for --spec parsing.", "parsing"),
}


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("case", sorted(DROPPED))
def test_a_spec_flag_read_as_prose_never_uses_the_session_spec(tmp_path, command, case):
    args, word = DROPPED[case]
    proj, result = _submit(tmp_path, f"/{command} {args}", [SESSION_SPEC], [SESSION_SPEC])
    assert result.returncode == 0, result.stderr
    assert _spec_lines(result.stdout) == ["Spec: none"]
    assert f'NOTE: "--spec {word}" was read as text' in result.stdout


@pytest.mark.parametrize("case", sorted(DROPPED))
def test_a_spec_flag_read_as_prose_never_uses_the_session_spec_dev_overnight(tmp_path, case):
    args, word = DROPPED[case]
    proj, result = _submit(tmp_path, f"/dev-overnight 23:59 {args}", [SESSION_SPEC], [SESSION_SPEC],
                           git=True)
    assert result.returncode == 0, result.stderr
    assert _spec_lines(result.stdout) == ["Spec: none"]
    assert f'NOTE: "--spec {word}" was read as text' in result.stdout
    state = json.loads((proj / ".claude" / f"overnight-state-{SID}.json").read_text())
    assert (state["spec_mode"], state["user_spec_path"]) == ("autonomous", None)


def test_a_glued_prose_dash_keeps_the_session_spec(tmp_path):
    # `API—spec section` is no flag at all: the session's spec stays the run's spec.
    proj, result = _submit(tmp_path, f"/dev {PROSE['em_dash_prose']}", [SESSION_SPEC], [SESSION_SPEC])
    assert result.returncode == 0, result.stderr
    assert _spec_lines(result.stdout) == [f"Spec: {proj / SESSION_SPEC}"]
