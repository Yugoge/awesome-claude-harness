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
