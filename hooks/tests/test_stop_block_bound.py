"""The Stop gate's block text is bounded: a span with thousands of gaps gets the todo lines and the refusal hint
first, the GAP lines counted by (problem, lane) with samples, and the path of a file that holds every line; a block
under the bound is today's text byte for byte."""
import importlib.util
import os
import re
import sys
from collections import Counter
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))
_spec = importlib.util.spec_from_file_location("stop_gate_bound", HOOKS / "stop-command-gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

HINT = 'A hook refused this step\'s own call. To end the turn, write the line "REFUSED: Step 10: x", ...\n'
TODO = ["todo: not completed: Step 10: Delegate to dev subagent", "todo: not completed: Step 11: Write the report"]


def _gaps(n):
    kinds = ("ABSENT_DECLARED_PATH", "MISSING_ARTIFACT", "UNRESOLVED_BLOCKERS")
    return TODO + [f"GAP artifact=docs/dev/dev-report-T-r{i % 16:02d}.json problem={kinds[i % 3]}: "
                   f"declares 'tests/unit/test_{i}.py', which does not exist on disk lane={'r%02d' % (i % 16) if i % 5 else '-'}"
                   for i in range(n)]


def _old(command, gaps, hint):  # the text before the bound, as it was built
    finish = "What a rule refuses is reported as refused, with the hook's output; nobody is asked about it."
    return (f"COMMAND_GATE /{command}: not complete\n" + "".join(f"- {g}\n" for g in gaps)
            + f"Finish the gaps above. {finish}\n" + hint)


def test_thousands_of_gaps_give_a_bounded_block_that_leads_with_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    gaps = _gaps(3000)
    text = gate._block_text("dev", gaps, HINT, "sess/1")
    assert len(text) <= gate.BLOCK_BOUND and len(_old("dev", gaps, HINT)) > 50 * gate.BLOCK_BOUND
    lines = text.splitlines(keepends=True)
    assert lines[0] == "COMMAND_GATE /dev: not complete\n"
    assert lines[1:3] == [f"- {t}\n" for t in TODO] and lines[3] == HINT
    groups = Counter(gate._GAP_KIND.match(g).groups() for g in gaps[2:])
    shown = {(k, l): int(n) for n, k, l in re.findall(r"^- (\d+) x problem=(\S+) lane=(\S+)$", text, re.M)}
    more = re.search(r"^- \.\.\. (\d+) more groups", text, re.M)
    assert all(groups[key] == n for key, n in shown.items())
    assert len(shown) + (int(more.group(1)) if more else 0) == len(groups)
    assert f"{len(gaps) - 2} GAP lines in {len(groups)} groups" in text
    path = gate.gaps_file("sess/1")
    assert os.path.dirname(path) == str(tmp_path / "state") and path in text
    written = Path(path).read_text(encoding="utf-8")
    assert written == "COMMAND_GATE /dev: not complete\n" + "".join(f"- {g}\n" for g in gaps)


def test_a_small_span_keeps_todays_text_byte_for_byte_and_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    for hint in ("", HINT):
        gaps = _gaps(20)
        assert gate._block_text("dev", gaps, hint, "s") == _old("dev", gaps, hint)
        assert gate._block_text("dev", gaps) == _old("dev", gaps, "")
    assert not (tmp_path / "state").exists()
