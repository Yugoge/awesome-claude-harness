"""P1 acceptance 5: every obligation template the command prose ships parses.

Two template forms exist: literal ``<obligation v="1">`` blocks, and the
one-line prose form ``role="x", pipeline="y", profile="a"/"b", ...
artifacts=[...]``. Placeholders are filled the way an orchestrator fills
them (ids with a valid task id, dispatched_at with now, the BULK=false form
of a conditional value) and the result must parse against the harness's own
schema registry.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks"))

from lib import obligation, schema_registry  # noqa: E402

FILES = ("dev.md", "dev-command.md", "dev-overnight.md", "close.md", "commit.md")
TASK_ID = "20261019-101010"
BLOCK_RE = re.compile(r'<obligation v="1">\s*(\{\s*".*?\})\s*</obligation>', re.S)
PROSE_RE = re.compile(
    r'role="([a-z-]+)", pipeline="([a-z-]+)", profile="([a-z_-]+)"(?:/"([a-z_-]+)")?[^\n]*?artifacts=\['
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fill(text: str) -> str:
    text = re.sub(r'<("[^"]*") when BULK=false, else [^>]*>', r"\1", text)
    text = re.sub(r'("dispatched_at"\s*:\s*)"[^"]*"', rf'\1"{_now()}"', text)
    text = text.replace("{pipeline.timestamp_suffix}", f"{TASK_ID}-1")
    text = re.sub(r'<TASK_ID or \\"bulk\\">', TASK_ID, text)
    text = text.replace("$TASK_ID", TASK_ID)
    return re.sub(r"<[A-Za-z_][^<>\"]*>", TASK_ID, text)


def _array_at(text: str, start: int) -> str:
    """The JSON array literal that opens at text[start] == '['."""
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            escaped = char == "\\" and not escaped
            if char == '"' and not escaped:
                in_string = False
            continue
        if char == '"':
            in_string, escaped = True, False
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise AssertionError(f"unterminated artifacts array at offset {start}")


def _templates():
    for name in FILES:
        text = (ROOT / "commands" / name).read_text(encoding="utf-8")
        for match in BLOCK_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield f"{name}:{line}:block", _fill(match.group(1))
        for match in PROSE_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            artifacts = _fill(_array_at(text, match.end() - 1))
            # The overnight prose binds task_id to the pipeline's own suffix.
            bound = f"{TASK_ID}-1" if "{pipeline.timestamp_suffix}" in match.group(0) else TASK_ID
            for profile in filter(None, match.group(3, 4)):
                doc = {"task_id": bound, "role": match.group(1), "pipeline": match.group(2),
                       "profile": profile, "dispatched_at": _now(), "artifacts": json.loads(artifacts)}
                yield f"{name}:{line}:prose:{profile}", json.dumps(doc)


TEMPLATES = list(_templates())


def test_every_command_carries_obligation_templates():
    found = {label.split(":", 1)[0] for label, _ in TEMPLATES}
    assert found == set(FILES), found
    assert len(TEMPLATES) >= 20


@pytest.mark.parametrize("label,body", TEMPLATES, ids=[label for label, _ in TEMPLATES])
def test_template_parses_against_the_harness_registry(label, body):
    parsed = obligation.parse_obligation(
        f'<obligation v="1">{body}</obligation>',
        known_schema_ids=frozenset(schema_registry.load_registry()),
    )
    assert isinstance(parsed, obligation.ParsedObligation), (label, parsed)
    doc = parsed.obligation
    for artifact in doc["artifacts"]:
        if artifact["kind"] == "json":
            # The identity the file must carry agrees with the obligation's task id
            # and with the file name the producer writes.
            assert set(artifact["identity"].values()) == {doc["task_id"]}, (label, artifact)
            assert doc["task_id"] in artifact["path"], (label, artifact)
            if label.split(":", 1)[0] in FILES[:3]:  # row 17: the dev commands name task_id
                assert "task_id" in artifact["identity"], (label, artifact)


def test_no_template_declares_required_values_or_a_json_waiver():
    lines = subprocess.run(
        ["git", "grep", "-n", "required_values", "--", "commands", "agents"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    assert lines == ""
    doc = {"task_id": TASK_ID, "role": "dev", "pipeline": "dev", "profile": "singular",
           "dispatched_at": _now(), "artifacts": [
               {"kind": "json", "path": f"docs/dev/dev-report-{TASK_ID}.json", "schema": "dev-report.v2",
                "identity": {"task_id": TASK_ID}, "required_values": {"dev.status": ["completed"]}}]}
    parsed = obligation.parse_obligation(f'<obligation v="1">{json.dumps(doc)}</obligation>')
    assert isinstance(parsed, obligation.Rejection) and parsed.reason == "unknown_field"
