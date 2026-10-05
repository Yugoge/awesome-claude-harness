"""Round-open recognition in hooks/lib/close-verdict.py (lane L5, AC10).

`CLOSE_FINDINGS: <n> items` is the never-landing return of a QA judging round
that opened findings. It must classify `no` (never `yes`) even when an earlier,
append-only section of the same close-report ended with a landed `CLOSE: YES`.
"""
import json
import re
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERDICT_PY = ROOT / "hooks" / "lib" / "close-verdict.py"
CLOSE_MD = ROOT / "commands" / "close.md"

cv = SourceFileLoader("close_verdict_round_open", str(VERDICT_PY)).load_module()

YES_FORMS = [
    "CLOSE: YES",
    "CLOSE: YES - with disclosures: 2 items",
    "CLOSE: YES - degraded codex consultation: codex_status=failed_quota",
    "CLOSE: YES — codex disabled by user",
    "CLOSE: YES (FORCED)",
]


def _report(final_line, trailing_yes=False):
    text = (
        "# Close Debate Report\nattempt 1\n\nCLOSE: YES\n\n"
        "## Attempt 2 (re-opened)\nQA prose may quote `CLOSE: YES` branches.\n\n"
        + final_line + "\n"
    )
    if trailing_yes:
        text += "\n## Attempt 3\nfixed and re-judged\n\nCLOSE: YES\n"
    return text


def test_round_open_line_classifies_no():
    assert cv.classify_line("CLOSE_FINDINGS: 2 items") == "no"
    assert cv.classify_line("CLOSE_FINDINGS: 1 item") == "no"


def test_round_open_report_never_reads_yes(tmp_path):
    report = _report("CLOSE_FINDINGS: 2 items")
    assert cv.classify_text(report) == "no"
    f = tmp_path / "close-report-x.md"
    f.write_text(report, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(VERDICT_PY), "classify-file", str(f)],
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == "no"


def test_later_landed_yes_after_round_open_reads_yes():
    assert cv.classify_text(_report("CLOSE_FINDINGS: 2 items", trailing_yes=True)) == "yes"


def test_non_numeric_is_not_round_open():
    assert cv.classify_line("CLOSE_FINDINGS: x items") == "unknown"
    # strict path unknown -> tolerant fallback still scans the whole text
    assert cv.classify_text(_report("CLOSE_FINDINGS: x items")) == "yes"


def test_legacy_classifications_unchanged():
    assert cv.classify_line("CLOSE: YES") == "yes"
    assert cv.classify_line("CLOSE: YES (FORCED)") == "yes"
    assert cv.classify_line("CLOSE: YES - degraded codex consultation: codex_status=failed_parse") == "yes"
    assert cv.classify_line("CLOSE: NO - r") == "no"
    assert cv.classify_text("**CLOSE: YES**") == "yes"
    assert cv.classify_text("") == "unknown"
    assert cv.classify_line("") == "unknown"


def _qa_regexes():
    text = CLOSE_MD.read_text(encoding="utf-8")
    start = text.index('<obligation v="1">\n{"task_id":"<TASK_ID>","role":"qa"')
    block = text[start:text.index("</obligation>", start)]
    body = block.split("\n", 1)[1]
    data = json.loads(body)
    regs = [a["terminal_line_regex"] for a in data["artifacts"]]
    assert len(regs) == 2
    return [re.compile(r) for r in regs]


def test_qa_obligation_regexes_accept_round_open_and_yes_not_no():
    for rx in _qa_regexes():
        assert rx.search("CLOSE_FINDINGS: 3 items")
        for line in YES_FORMS:
            assert rx.search(line), line
        assert not rx.search("CLOSE: NO")
        assert not rx.search("CLOSE: NO - reason")
