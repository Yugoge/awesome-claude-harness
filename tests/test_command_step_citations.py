"""A command text that cites another command's numbered step or rule cites one that exists.

Measured on 1ace5ee4: `commands/do.md` Step 3 said "Classify findings per `commands/codex.md` Rule 3",
and since P12-L2 codex.md has no Rule 3 (0 matches); it never named
`templates/prompt-includes/codex-consultation.md`, which D31 makes the one home of the Codex calling
protocol (review comment on #31). Now Step 3 says Codex calls follow that include and adds only what
/do adds, and every `commands/<name>.md` Step or Rule a prompt cites is a heading of that file.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = "templates/prompt-includes/codex-consultation.md"
CITATION_RE = re.compile(r"`commands/([a-z0-9-]+\.md)` (Step|Rule) (\d+)\b")


def _step3(text: str) -> str:
    return re.search(r"^### Step 3:.*?(?=^### Step 4:)", text, re.S | re.M).group(0)


def test_do_step3_follows_the_codex_include():
    step3 = _step3((ROOT / "commands" / "do.md").read_text())
    assert INCLUDE in step3 and (ROOT / INCLUDE).is_file()
    assert "Rule 3" not in (ROOT / "commands" / "do.md").read_text()
    # what /do adds to the include: its scope, its fixes, its listing
    assert "Step 2's changes" in step3
    assert "Fix `in_scope_real_bug` findings" in step3
    assert "`out_of_scope` findings" in step3 and "unfixed and list them in the Step 4 summary" in step3
    assert ('If codex fails (quota/timeout/parse): record `codex_consult: {status: "<failed_quota|failed_timeout|'
            'failed_parse>", note: "<verbatim error>"}` in the do-report and proceed.') in step3


def test_every_cited_step_or_rule_is_a_heading_of_the_cited_command():
    texts = [p for d in ("commands", "agents", "templates", "skills") for p in (ROOT / d).rglob("*.md")]
    dangling = []
    for path in texts:
        for name, kind, number in CITATION_RE.findall(path.read_text()):
            cited = ROOT / "commands" / name
            if not cited.is_file() or not re.search(rf"^#+ .*\b{kind} {number}\b", cited.read_text(), re.M):
                dangling.append(f"{path.relative_to(ROOT)}: commands/{name} {kind} {number}")
    assert not dangling, dangling
