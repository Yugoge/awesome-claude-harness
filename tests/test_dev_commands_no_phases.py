"""The /dev-family command files open with frontmatter the CLI can parse.

The frontmatter of the five /dev-family command files must parse as YAML and hold a non-empty `description` and
`disable-model-invocation` (a colon and a space inside a plain description once made redev.md's invalid and nothing
caught it). The tests at the end feed the helper deliberately bad frontmatter and require every one to be flagged.

This file used to also grep these commands for the owner's no-phases ruling (D33). No hook, script or replay reads
those sentences, so those greps were deleted (P15-L8); the ruling lives in prompt text only (agents/shared/no-phases.md
and the lines that point at it). Its one code consumer, the replay /spec driver's split-QA check, is run by
tests/test_no_phases_spec_command.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands"


def _read(name: str) -> str:
    return (COMMANDS / name).read_text(encoding="utf-8")


FRONTMATTER_FILES = ("dev.md", "dev-command.md", "dev-overnight.md", "redev.md", "do.md")
_FRONTMATTER = re.compile(r"---\n(.*?)\n---[ \t]*(?:\n|$)", re.S)


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that also refuses a key given twice (PyYAML otherwise keeps the last one silently)."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=True) for key, _ in node.value]
        twice = sorted({str(k) for k in keys if keys.count(k) > 1})
        if twice:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {twice}", node.start_mark)
        return super().construct_mapping(node, deep)


def frontmatter_problems(text: str) -> list[str]:
    """The frontmatter parses as YAML and holds a non-empty string `description` and `disable-model-invocation`."""
    block = _FRONTMATTER.match(text)
    if block is None:
        return ["no frontmatter block between two '---' lines at the top"]
    try:
        data = yaml.load(block.group(1), Loader=_StrictLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as err:
        return [f"the frontmatter is not valid YAML: {' '.join(str(err).split())}"]
    if not isinstance(data, dict):
        return [f"the frontmatter is a {type(data).__name__}, not a mapping"]
    problems = [f"no {key!r} key" for key in ("description", "disable-model-invocation") if key not in data]
    if "description" in data and not (isinstance(data["description"], str) and data["description"].strip()):
        problems.append(f"'description' is {data['description']!r}, not a non-empty string")
    return problems


@pytest.mark.parametrize("name", FRONTMATTER_FILES)
def test_the_frontmatter_of_each_command_file_parses_as_yaml(name: str) -> None:
    assert frontmatter_problems(_read(name)) == []


# === mutation evidence: the helper must flag deliberately bad frontmatter ===================================

# a description whose plain scalar holds a colon and a space: not valid YAML (the redev.md defect)
_COLON_IN_PLAIN_SCALAR = (
    "---\n"
    "description: /redev is /dev when saving context: it re-enters the harness in the same conversation\n"
    'argument-hint: "[--codex] [--spec <path>] [<requirement>]"\n'
    "disable-model-invocation: true\n"
    "---\n\nBody.\n")


def test_the_frontmatter_helper_flags_a_colon_and_a_space_inside_a_plain_description() -> None:
    problems = frontmatter_problems(_COLON_IN_PLAIN_SCALAR)
    assert len(problems) == 1 and "not valid YAML" in problems[0], problems
    # the same description with the colon replaced (the repair), or quoted, is accepted
    assert frontmatter_problems(_COLON_IN_PLAIN_SCALAR.replace("context: it", "context - it")) == []
    assert frontmatter_problems(_COLON_IN_PLAIN_SCALAR.replace("description: /redev", 'description: "/redev').replace(
        "conversation\n", 'conversation"\n', 1)) == []


@pytest.mark.parametrize("bad,expected", [
    ("---\ndescription: x\n---\nBody.\n", "no 'disable-model-invocation' key"),
    ("---\ndisable-model-invocation: true\n---\nBody.\n", "no 'description' key"),
    ("---\ndescription:\ndisable-model-invocation: true\n---\nBody.\n", "not a non-empty string"),
    ("---\ndescription: '  '\ndisable-model-invocation: true\n---\nBody.\n", "not a non-empty string"),
    ("---\ndescription: 12\ndisable-model-invocation: true\n---\nBody.\n", "not a non-empty string"),
    ("---\ndescription: a\ndescription: b\ndisable-model-invocation: true\n---\nBody.\n", "duplicate key"),
    ("---\n- description\n- disable-model-invocation\n---\nBody.\n", "not a mapping"),
    ("description: x\ndisable-model-invocation: true\n\nBody.\n", "no frontmatter block"),
], ids=["no-disable-key", "no-description-key", "null-description", "blank-description", "number-description",
        "duplicate-key", "list", "no-fence"])
def test_the_frontmatter_helper_flags_a_missing_key_an_empty_description_or_a_broken_block(bad: str,
                                                                                             expected: str) -> None:
    problems = frontmatter_problems(bad)
    assert any(expected in p for p in problems), problems
