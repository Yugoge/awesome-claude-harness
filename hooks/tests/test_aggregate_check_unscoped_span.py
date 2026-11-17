"""OB-L42 (AG-GLOBAL-SCAN): G3's QA collection check
(hooks/pretool-aggregate-check.py) on a QA dispatch with no obligation.

Such a dispatch names no cycle. Outside every command span another cycle's
abandoned fan-out in docs/dev is not its to collect: the global scan warns
(exit 0, the finding on stderr) instead of blocking. Inside a command span
(/dev, /dev-overnight) the scan still blocks, and a dispatch whose obligation
names a cycle without its canonical is still refused.

Run with: python3 -m pytest hooks/tests/test_aggregate_check_unscoped_span.py -v
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCOPE = Path(__file__).resolve().parent / "test_aggregate_check_obligation_scope.py"
_spec = importlib.util.spec_from_file_location("_g3_scope_helpers", _SCOPE)
scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scope)

ABANDONED = scope.OTHER
TASK = scope.TASK
LANES = scope.LANES


def _typed(name, args="implement the requirement"):
    """A human-typed harness command and its isMeta command body."""
    return [
        {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
         "message": {"role": "user", "content":
                     f"<command-message>{name}</command-message>\n"
                     f"<command-name>/{name}</command-name>\n<command-args>{args}</command-args>"}},
        {"type": "user", "isSidechain": False, "isMeta": True,
         "message": {"role": "user", "content": [{"type": "text", "text": f"Command body of {name}."}]}},
    ]


def _plain(text="please verify the last change"):
    return {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
            "message": {"role": "user", "content": text}}


def _transcript(tmp_path, records):
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _run(project, prompt, transcript, mode=None):
    """scope._run with the dispatch's transcript_path set."""
    original = scope.subprocess.run

    def run(cmd, input=None, **kw):
        payload = json.loads(input)
        payload["transcript_path"] = str(transcript)
        return original(cmd, input=json.dumps(payload), **kw)

    scope.subprocess.run = run
    try:
        return scope._run(project, prompt, mode)
    finally:
        scope.subprocess.run = original


@pytest.fixture
def dev_dir(tmp_path):
    path = tmp_path / "docs" / "dev"
    path.mkdir(parents=True)
    return path


# --------------------------------------------------------------------------
# The lifted over-block: red on the base, green after OB-L42.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [None, "block"])
def test_unscoped_qa_outside_any_span_warns_on_an_abandoned_fanout(dev_dir, tmp_path, mode):
    canonical = scope._fanout(dev_dir, ABANDONED, LANES)  # every lane reported, canonical never written
    transcript = _transcript(tmp_path, [_plain()])
    result = _run(dev_dir.parents[1], "Verify the implementation.", transcript, mode)
    assert result.returncode == 0, result.stderr
    assert "BLOCKED" not in result.stderr
    assert "WARNING (not blocking)" in result.stderr
    assert f"[canonical_missing] {canonical}" in result.stderr


# --------------------------------------------------------------------------
# Must still refuse.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command", ["dev", "dev-overnight"])
@pytest.mark.parametrize("mode", [None, "block"])
def test_unscoped_qa_inside_a_dev_span_still_blocks(dev_dir, tmp_path, command, mode):
    canonical = scope._fanout(dev_dir, ABANDONED, LANES)
    transcript = _transcript(tmp_path, [_plain(), *_typed(command), _plain("continue")])
    result = _run(dev_dir.parents[1], "Verify the implementation.", transcript, mode)
    assert result.returncode == 2
    assert "BLOCKED Agent dispatch (qa)" in result.stderr
    assert f"[canonical_missing] {canonical}" in result.stderr


@pytest.mark.parametrize("mode", [None, "block"])
def test_obligated_qa_whose_cycle_lacks_its_canonical_still_blocks_outside_any_span(dev_dir, tmp_path, mode):
    canonical = scope._fanout(dev_dir, TASK, LANES)
    transcript = _transcript(tmp_path, [_plain()])
    result = _run(dev_dir.parents[1], scope._obligation(TASK), transcript, mode)
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr


@pytest.mark.parametrize("mode", [None, "block"])
def test_obligated_qa_whose_cycle_lacks_its_canonical_still_blocks_inside_a_dev_span(dev_dir, tmp_path, mode):
    canonical = scope._fanout(dev_dir, TASK, LANES)
    transcript = _transcript(tmp_path, [*_typed("dev")])
    result = _run(dev_dir.parents[1], scope._obligation(TASK), transcript, mode)
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr


def test_unscoped_qa_with_an_unreadable_transcript_keeps_the_conservative_scan(dev_dir, tmp_path):
    """A span that cannot be read is unknown, not absent: the scan still blocks."""
    canonical = scope._fanout(dev_dir, ABANDONED, LANES)
    result = _run(dev_dir.parents[1], "Verify the implementation.", tmp_path / "missing.jsonl")
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr
