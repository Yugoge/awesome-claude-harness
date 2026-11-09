"""/test's failure routes: no typed menu or exit option, and only executor statuses the executor emits (D23, D25)."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_MD = ROOT / "commands" / "test.md"
EXECUTOR_MD = ROOT / "agents" / "test-executor.md"


def _step(text: str, number: int) -> str:
    match = re.search(rf"^### Step {number}:.*?(?=^### |^## |\Z)", text, re.M | re.S)
    assert match, f"commands/test.md has no Step {number}"
    return match.group(0)


def test_step_15_asks_in_turn_and_offers_no_exit() -> None:
    step = _step(TEST_MD.read_text(encoding="utf-8"), 15)
    assert "AskUserQuestion" in step
    assert "Step 10" in step and "Step 16" in step
    exit_menu = re.compile(r"Select option|\[1-\d\]|Ignore failures|Cancel\b|Exit without report|report and exit")
    assert exit_menu.findall(step) == []


def test_every_executor_status_test_md_reads_is_one_the_executor_emits() -> None:
    emitted_match = re.search(r'"executor":\s*\{\s*"status":\s*"([^"]+)"', EXECUTOR_MD.read_text(encoding="utf-8"))
    assert emitted_match, "agents/test-executor.md declares no executor.status"
    emitted = set(emitted_match.group(1).split("|"))
    read = set(re.findall(r'executor\.status == "([^"]+)"', TEST_MD.read_text(encoding="utf-8")))
    assert read, "commands/test.md reads no executor.status"
    assert read <= emitted, f"read but never emitted: {sorted(read - emitted)}"
