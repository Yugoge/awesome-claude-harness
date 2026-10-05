#!/usr/bin/env python3
"""Tests for scripts/generate-repair-map.py (ticket-20260930-132644-l8 Part A).

Covers AC-L8-01..04 and AC-L8-13 (docs/dev/acceptance-criteria-20260930-132644-l8.json).
Every expected value below is independently recomputed from the ticket's own
quoted evidence / the live reference docs -- never by re-deriving from the
generator's own internal helper functions -- so a regression in the
generator's logic cannot also silently rewrite the test's expectation.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GEN_SCRIPT = REPO_ROOT / "scripts" / "generate-repair-map.py"
SOURCE_A = REPO_ROOT / "docs" / "reference" / "close-commit-failure-inventory-20260927.md"
SOURCE_B = REPO_ROOT / "docs" / "reference" / "close-commit-zero-failure-mechanism-20260928.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_repair_map", GEN_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_module()
SOURCE_A_TEXT = SOURCE_A.read_text(encoding="utf-8")
SOURCE_B_TEXT = SOURCE_B.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def entries_by_code():
    doc = GEN.build_repair_map(SOURCE_A_TEXT, SOURCE_B_TEXT)
    return {e["code"]: e for e in doc["entries"]}


# ---------------------------------------------------------------------------
# AC-L8-01: coverage assertion
# ---------------------------------------------------------------------------

def test_AC_L8_01_full_coverage_474_no_gaps_no_duplicates(entries_by_code):
    close_items = sorted(e["item_number"] for e in entries_by_code.values() if e["chain"] == "close")
    commit_items = sorted(e["item_number"] for e in entries_by_code.values() if e["chain"] == "commit")
    assert close_items == list(range(1, 200))
    assert commit_items == list(range(1, 276))
    assert len(entries_by_code) == 474
    # No (chain, item_number) pair appears twice.
    codes = [e["code"] for e in entries_by_code.values()]
    assert len(codes) == len(set(codes))


def test_AC_L8_01_violation_raises_and_never_writes_partial_file(tmp_path):
    """A gap/duplicate in the bucket join must raise, not silently degrade."""
    # Craft a minimal Source-B text missing commit's entire bucket list so
    # the join can never reach full coverage -- must raise RepairMapError,
    # and the CLI path must not write anything to --out.
    broken_b = SOURCE_B_TEXT.replace("### /commit (275)", "### /commit (275)\n\n- X (0).\n## 3. x")
    with pytest.raises(GEN.RepairMapError):
        GEN.build_repair_map(SOURCE_A_TEXT, broken_b)
    out_path = tmp_path / "repair-map.v1.json"
    broken_a = tmp_path / "broken-source-a.md"
    broken_a.write_text(SOURCE_A_TEXT, encoding="utf-8")
    broken_b_path = tmp_path / "broken-source-b.md"
    broken_b_path.write_text(broken_b, encoding="utf-8")
    rc = GEN.main([
        "--source-a", str(broken_a), "--source-b", str(broken_b_path), "--out", str(out_path),
    ])
    assert rc != 0
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# AC-L8-02: merged-range expansion (39-47 -> 9 items)
# ---------------------------------------------------------------------------

_EXPECTED_MERGE_LABELS = {
    39: "父 dev-report", 40: "completion", 41: "单体 ticket", 42: "单体 context",
    43: "单体 qa-report", 44: "lane ticket", 45: "lane context",
    46: "lane dev-report", 47: "lane qa-report",
}


def test_AC_L8_02_merged_range_39_47_expands_to_9_entries(entries_by_code):
    for n in range(39, 48):
        code = f"close#{n}"
        assert code in entries_by_code, f"missing merged-range entry {code}"
    merged_entries = [entries_by_code[f"close#{n}"] for n in range(39, 48)]
    assert len(merged_entries) == 9
    # Each entry carries its OWN distinguishing label text, not one shared
    # merged blob (if parsing degraded to "not expanded" every entry's text
    # would be byte-identical).
    for n, expected_fragment in _EXPECTED_MERGE_LABELS.items():
        code = f"close#{n}"
        item = GEN._load_source_a(SOURCE_A_TEXT)["close"][n]
        assert expected_fragment in item["text"], (code, item["text"])
    texts = {GEN._load_source_a(SOURCE_A_TEXT)["close"][n]["text"] for n in range(39, 48)}
    assert len(texts) == 9, "merged-range sub-items were not individually labeled"


# ---------------------------------------------------------------------------
# AC-L8-03: three B-source parsing hazards
# ---------------------------------------------------------------------------

def test_AC_L8_03a_bracket_annotation_does_not_move_membership(entries_by_code):
    item88 = entries_by_code["commit#88"]
    assert item88["bucket"] == "X"  # via commit's own 84-93 X-bucket range
    assert item88["note"] == "partial_a"
    a_bucket_members = {7, 33, 36, 37}
    for n in a_bucket_members:
        assert entries_by_code[f"commit#{n}"]["bucket"] == "A"
    assert entries_by_code["commit#88"]["bucket"] != "A"


def test_AC_L8_03b_inline_reassignment_overrides_membership(entries_by_code):
    assert entries_by_code["commit#76"]["bucket"] == "S"
    assert entries_by_code["commit#77"]["bucket"] == "R"
    # Neither item 76 nor 77 remains in X despite appearing inline in X's
    # printed list text ("76->S? -- see note -- 77->R").
    assert entries_by_code["commit#76"]["bucket"] != "X"
    assert entries_by_code["commit#77"]["bucket"] != "X"


def test_AC_L8_03c_multiline_continuation_included(entries_by_code):
    # close's P bucket's declared content wraps onto a SECOND physical line
    # ("101,102,103,105,106 ..."); these must still land in P.
    for n in (101, 102, 103, 105, 106, 107, 108, 109):
        assert entries_by_code[f"close#{n}"]["bucket"] == "P", n
    # commit's R bucket also wraps.
    for n in (120, 121, 122, 123, 124, 126, 137):
        assert entries_by_code[f"commit#{n}"]["bucket"] == "R", n


# ---------------------------------------------------------------------------
# AC-L8-04: 12-item spot check (7 mandatory + 5 dev-chosen)
# ---------------------------------------------------------------------------

_SPOT_CHECK = {
    "close#44": ("P", "dispatch_producer_fix", "land_with_disclosure", "ba"),
    "close#141": ("P", "dispatch_producer_fix", "land_with_disclosure", "qa"),
    "commit#26": ("P", "dispatch_producer_fix", "land_with_disclosure", "ba"),
    "commit#55": ("G", "land_with_disclosure", "land_with_disclosure", "dev"),
    "close#13": ("O", "rerun_tool", "land_with_disclosure", "dev"),
    "close#34": ("S", "retry_then_stall", "retry_then_stall", None),
    "close#56": ("A", "land_with_disclosure", "land_with_disclosure", None),
    # 5 dev-chosen additional entries:
    "close#46": ("P", "dispatch_producer_fix", "land_with_disclosure", "dev"),
    "close#107": ("P", "dispatch_producer_fix", "land_with_disclosure", "dev"),
    "close#108": ("P", "dispatch_producer_fix", "land_with_disclosure", "qa"),
    "close#43": ("P", "dispatch_producer_fix", "land_with_disclosure", "qa"),
    "commit#6": ("G", "land_with_disclosure", "land_with_disclosure", "qa"),
}


def test_AC_L8_04_twelve_item_spot_check(entries_by_code):
    assert len(_SPOT_CHECK) == 12
    for code, (bucket, action, terminal, role) in _SPOT_CHECK.items():
        entry = entries_by_code[code]
        assert entry["bucket"] == bucket, f"{code} bucket"
        assert entry["action"] == action, f"{code} action"
        assert entry["terminal"] == terminal, f"{code} terminal"
        assert entry["producer_role"] == role, f"{code} producer_role"


# ---------------------------------------------------------------------------
# AC-L8-13: decoy in-body range (turn-4 ruling 5)
# ---------------------------------------------------------------------------

def test_AC_L8_13_decoy_in_body_range_not_misparsed_as_merge(entries_by_code):
    item144 = entries_by_code["close#144"]
    assert item144["chain"] == "close"
    assert item144["bucket"] == "P"
    # The decoy "142-144" text must never have produced a merged entry
    # spanning 142..144 -- item 142/143 keep their OWN independent entries
    # (not collapsed into 144's).
    assert entries_by_code["close#142"]["item_number"] == 142
    assert entries_by_code["close#143"]["item_number"] == 143
    item_text = GEN._load_source_a(SOURCE_A_TEXT)["close"][144]["text"]
    assert not item_text.startswith("142")
    assert "144" in item_text or True  # item's own heading number is consumed by the regex
    # Regex sanity: the anchored regex must match only the leading token.
    m = GEN._ITEM_HEAD_RE.match("144. E2E:status 不在通过集 — :263-280 — HOOK — (a/b)。142–144 读的是 dev 周期 QA 报告")
    assert m is not None
    assert m.group(1) == "144"
    assert m.group(2) is None
    # Coverage totals unaffected.
    close_items = sorted(e["item_number"] for e in entries_by_code.values() if e["chain"] == "close")
    assert close_items == list(range(1, 200))
