#!/usr/bin/env python3
"""Generate schemas/repair-map.v1.json from the two close/commit reference docs.

Part A of ticket-20260930-132644-l8 (spec-20260930-092323 lane L8). Joins:
  Source A: docs/reference/close-commit-failure-inventory-20260927.md
            (474 numbered failure modes, a-e class only, no P/O/R/S/A/X/G bucket).
  Source B: docs/reference/close-commit-zero-failure-mechanism-20260928.md
            SS2 "Elimination accounting" (the P/O/R/S/A/X/G bucket lists).
on (chain, item_number) and asserts full coverage (close 1..199, commit
1..275, 474 total, zero gaps, zero double-assignment) before writing.

Usage: generate-repair-map.py [--source-a PATH] [--source-b PATH] [--out PATH] [--check]
Exit codes: 0=written (or --check passed), 1=coverage/parse violation (nothing written)

Deliberate BA-flagged judgment calls (ticket Technical Hints SSA3, Edge Case 1/2):
  - producer_role derivation drops the design table's bare "status" keyword
    trigger for changelog-analyst (see _derive_producer_role docstring) --
    matching generic "status" would misattribute "dev.status"/"qa.status"
    text across most of the inventory.
  - `recheck` mirrors `action` (no separate recheck-command grammar is
    pinned anywhere in the design docs); both fields are present per
    Technical Hints SSA2's required entry shape.
  - per-bucket printed subtotals (e.g. /commit's "R (37)" header) are NEVER
    used as a validation gate (Edge Case 1) -- only the three grand totals
    (199/275/474) and zero-gap/zero-duplicate are authoritative.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_A = REPO_ROOT / "docs" / "reference" / "close-commit-failure-inventory-20260927.md"
DEFAULT_SOURCE_B = REPO_ROOT / "docs" / "reference" / "close-commit-zero-failure-mechanism-20260928.md"
DEFAULT_OUT = REPO_ROOT / "schemas" / "repair-map.v1.json"

CHAIN_MAX = {"close": 199, "commit": 275}


class RepairMapError(Exception):
    """Coverage or parse violation -- caller must exit nonzero, write nothing."""


# ---------------------------------------------------------------------------
# Source A: per-item reference text (docs/reference/close-commit-failure-
# inventory-20260927.md). Line-start-anchored per ruling 5 -- an in-body
# decoy numeric range (e.g. item #144's own "142-144 读的是...") must never
# be mistaken for a merged-range heading (AC13).
# ---------------------------------------------------------------------------

_ITEM_HEAD_RE = re.compile(r"^(\d+)(?:[–-](\d+))?\.\s*(.*)$")


def _parse_source_a_section(section_text: str) -> dict[int, dict]:
    """Return {item_number: {"text": str, "merged": bool}} for one chain's
    Source-A subsection. A merged-range heading (e.g. "39-47. ...") expands
    to one entry per member, each carrying its own sub-list label; a normal
    heading is a singular entry carrying its own full line text."""
    items: dict[int, dict] = {}
    current_numbers: list[int] | None = None
    current_is_merge = False
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_numbers, current_is_merge, current_lines
        if current_numbers is None:
            return
        full_text = " ".join(current_lines).strip()
        if current_is_merge:
            # The FIRST sub-item's own number+label is glued directly onto
            # the heading's intro text with no leading "·" separator (e.g.
            # "...均 (b): 39 父 dev-report(...) · 40 completion · ..."), so a
            # naive split("·") merges the intro into sub-item 39's chunk and
            # _SUBLABEL_RE (anchored at chunk start) never matches it. Search
            # for each target number directly instead, bounded so a 2-digit
            # member number never partially matches inside a longer one.
            labels: dict[int, str] = {}
            for n in current_numbers:
                m = re.search(rf"(?<!\d){n}(?!\d)\s+([^·]+?)\s*(?=·|$)", full_text)
                if m:
                    labels[n] = m.group(1).strip()
            for n in current_numbers:
                items[n] = {"text": labels.get(n, full_text), "merged": True}
        else:
            items[current_numbers[0]] = {"text": full_text, "merged": False}
        current_numbers = None
        current_lines = []

    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # Subsection header -- ends the current item's accumulation and
            # is never itself continuation text (it would otherwise bleed
            # unrelated prose into whichever item preceded it).
            flush()
            continue
        m = _ITEM_HEAD_RE.match(stripped)
        if m:
            flush()
            start = int(m.group(1))
            end = m.group(2)
            if end is not None:
                current_numbers = list(range(start, int(end) + 1))
                current_is_merge = True
            else:
                current_numbers = [start]
                current_is_merge = False
            current_lines = [m.group(3)]
            continue
        if current_numbers is not None:
            current_lines.append(stripped)
    flush()
    return items


def _load_source_a(text: str) -> dict[str, dict[int, dict]]:
    close_start = text.index("## 第一部分:/close(199 种)")
    commit_start = text.index("## 第二部分:/commit(275 种)")
    part3_idx = text.find("## 第三部分")
    close_text = text[close_start:commit_start]
    commit_text = text[commit_start:part3_idx] if part3_idx != -1 else text[commit_start:]
    return {
        "close": _parse_source_a_section(close_text),
        "commit": _parse_source_a_section(commit_text),
    }


# ---------------------------------------------------------------------------
# Source B: bucket membership (docs/reference/close-commit-zero-failure-
# mechanism-20260928.md SS2). Bucket bullets may wrap across multiple source
# lines before the next "- <LETTER> (" bullet or a section boundary (AC3c);
# a bracket annotation like "(plus half of 88)" attaches a note WITHOUT
# moving membership (AC3a); an inline marker like "76->S? -- see note --
# 77->R" OVERRIDES membership even when the target bucket's own printed list
# omits the item (AC3b).
# ---------------------------------------------------------------------------

_BUCKET_START_RE = re.compile(r"^-\s+([A-Z])\s*\((\d+)\)[.:]\s*(.*)$")
_PARTIAL_A_RE = re.compile(r"\(plus (?:half of|partial-a members of) ([\d,\s]+)\)")
_REASSIGN_RE = re.compile(r"(\d+)\s*→\s*([A-Z])\??")
_PAREN_RE = re.compile(r"\([^()]*\)")
_RANGE_RE = re.compile(r"(\d+)\s*[–-]\s*(\d+)")
_NUM_RE = re.compile(r"\d+")


def _parse_source_b_section(section_text: str) -> tuple[dict[str, set[int]], set[int]]:
    """Return (bucket_members, partial_a_item_numbers) for one chain."""
    bucket_members: dict[str, set[int]] = {}
    partial_a_notes: set[int] = set()
    reassignments: list[tuple[int, str]] = []

    current_letter: str | None = None
    current_declared_count: int | None = None
    current_content: list[str] = []

    def flush() -> None:
        nonlocal current_letter, current_declared_count, current_content
        if current_letter is None:
            return
        letter = current_letter
        bucket_members.setdefault(letter, set())
        if current_declared_count == 0:
            current_letter = None
            current_content = []
            return
        content = " ".join(current_content)

        def _capture_partial_a(m: re.Match) -> str:
            for tok in re.split(r"[,\s]+", m.group(1).strip()):
                if tok.isdigit():
                    partial_a_notes.add(int(tok))
            return " "

        content = _PARTIAL_A_RE.sub(_capture_partial_a, content)

        def _capture_reassign(m: re.Match) -> str:
            reassignments.append((int(m.group(1)), m.group(2)))
            return " "

        content = _REASSIGN_RE.sub(_capture_reassign, content)
        content = _PAREN_RE.sub(" ", content)

        def _capture_range(m: re.Match) -> str:
            a, b = int(m.group(1)), int(m.group(2))
            lo, hi = (a, b) if a <= b else (b, a)
            bucket_members[letter].update(range(lo, hi + 1))
            return " "

        content = _RANGE_RE.sub(_capture_range, content)
        for tok in _NUM_RE.findall(content):
            bucket_members[letter].add(int(tok))
        current_letter = None
        current_content = []

    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("##"):
            flush()
            break
        m = _BUCKET_START_RE.match(stripped)
        if m:
            flush()
            current_letter = m.group(1)
            current_declared_count = int(m.group(2))
            current_content = [m.group(3)]
            continue
        if stripped.startswith("- "):
            # A non-lettered bullet (e.g. "- Sum 55+2+...= 275.") terminates
            # the current bucket's accumulation without itself starting one.
            flush()
            continue
        if current_letter is not None:
            current_content.append(stripped)
    flush()

    for item_number, target_letter in reassignments:
        for letter, members in bucket_members.items():
            if letter != target_letter:
                members.discard(item_number)
        bucket_members.setdefault(target_letter, set()).add(item_number)

    return bucket_members, partial_a_notes


def _load_source_b(text: str) -> dict[str, tuple[dict[str, set[int]], set[int]]]:
    close_start = text.index("### /close (199)")
    commit_start = text.index("### /commit (275)")
    # Skip past each chain's own "### ..." header line itself -- otherwise
    # the per-line loop's own break-on-"##" boundary check (needed to stop
    # at the NEXT "## " section, e.g. "## 3. Design pre-mortem register")
    # would fire immediately on the header line that starts the slice.
    close_body_start = text.index("\n", close_start) + 1
    commit_body_start = text.index("\n", commit_start) + 1
    close_text = text[close_body_start:commit_start]
    commit_text = text[commit_body_start:]
    return {
        "close": _parse_source_b_section(close_text),
        "commit": _parse_source_b_section(commit_text),
    }


# ---------------------------------------------------------------------------
# Bucket -> action/terminal (Technical Hints SSA3) + producer_role (R1 step6)
# ---------------------------------------------------------------------------

_BUCKET_ACTION_TERMINAL = {
    "P": ("dispatch_producer_fix", "land_with_disclosure"),
    "R": ("rerun_tool", "land_with_disclosure"),
    "S": ("retry_then_stall", "retry_then_stall"),
    "A": ("land_with_disclosure", "land_with_disclosure"),
    "X": ("land_with_disclosure", "land_with_disclosure"),
    "G": ("land_with_disclosure", "land_with_disclosure"),
}


def _bucket_to_action_terminal(bucket: str, is_aggregator_reference: bool) -> tuple[str, str]:
    if bucket == "O":
        if is_aggregator_reference:
            return "rerun_tool", "land_with_disclosure"
        return "dispatch_producer_fix", "land_with_disclosure"
    try:
        return _BUCKET_ACTION_TERMINAL[bucket]
    except KeyError as exc:
        raise RepairMapError(f"unknown bucket letter {bucket!r}") from exc


def _derive_producer_role(text: str) -> str | None:
    """R1 step6 producer_role derivation applied to the item's own Source-A
    reference text. Deliberately narrower than the design table's bare
    "status" keyword for changelog-analyst (BA-flagged judgment call, see
    module docstring) -- only the explicit word "changelog" triggers it.
    Order matters: more specific artifact-kind words are checked first."""
    t = text.lower()
    if "qa-report" in t or "qa_report" in t:
        return "qa"
    if "close-report" in t or "close_report" in t:
        return "qa"
    if "test-writer" in t or "test_writer" in t:
        return "test-writer"
    if "dev-report" in t or "dev_report" in t or "canonical" in t:
        return "dev"
    if "ticket" in t or "context" in t or "acceptance-criteria" in t or "acceptance_criteria" in t:
        return "ba"
    if "changelog" in t:
        return "changelog-analyst"
    return None


def _is_aggregator_reference(text: str) -> bool:
    return "AGG" in text or "aggregate-dev-report" in text.lower()


# ---------------------------------------------------------------------------
# Join + coverage assertion (AC1) + entry construction
# ---------------------------------------------------------------------------

def build_repair_map(source_a_text: str, source_b_text: str) -> dict:
    source_a = _load_source_a(source_a_text)
    source_b = _load_source_b(source_b_text)

    entries = []
    for chain, expected_max in CHAIN_MAX.items():
        bucket_members, partial_a_notes = source_b[chain]
        item_to_bucket: dict[int, str] = {}
        for letter, members in bucket_members.items():
            for n in members:
                if n in item_to_bucket:
                    raise RepairMapError(
                        f"{chain}#{n} double-assigned to buckets "
                        f"{item_to_bucket[n]!r} and {letter!r}"
                    )
                item_to_bucket[n] = letter

        full_range = set(range(1, expected_max + 1))
        covered = set(item_to_bucket)
        missing = sorted(full_range - covered)
        out_of_range = sorted(covered - full_range)
        if missing:
            raise RepairMapError(f"{chain}: missing bucket assignment for items {missing}")
        if out_of_range:
            raise RepairMapError(f"{chain}: out-of-range item numbers {out_of_range}")

        items_text = source_a[chain]
        for n in range(1, expected_max + 1):
            bucket = item_to_bucket[n]
            text = items_text.get(n, {}).get("text", "")
            action, terminal = _bucket_to_action_terminal(bucket, _is_aggregator_reference(text))
            entries.append({
                "code": f"{chain}#{n}",
                "chain": chain,
                "item_number": n,
                "bucket": bucket,
                "producer_role": _derive_producer_role(text),
                "action": action,
                "recheck": action,
                "terminal": terminal,
                "note": "partial_a" if n in partial_a_notes else None,
            })

    if len(entries) != 474:
        raise RepairMapError(f"expected 474 total entries, computed {len(entries)}")

    return {
        "_kind": "data",
        "$comment": (
            "474-entry attribution/repair DATA table -- not a JSON-Schema "
            "document -- despite living under schemas/ and being registered "
            "in schemas/registry.json. See ticket-20260930-132644-l8.md "
            "Technical Hints SSA1."
        ),
        "generated_by": "scripts/generate-repair-map.py",
        "entry_count": len(entries),
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-a", type=Path, default=DEFAULT_SOURCE_A)
    parser.add_argument("--source-b", type=Path, default=DEFAULT_SOURCE_B)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="validate only, do not write")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        source_a_text = args.source_a.read_text(encoding="utf-8")
        source_b_text = args.source_b.read_text(encoding="utf-8")
        document = build_repair_map(source_a_text, source_b_text)
    except (RepairMapError, OSError, ValueError) as exc:
        sys.stderr.write(f"generate-repair-map: {exc}\n")
        return 1

    if args.check:
        sys.stderr.write(f"generate-repair-map: OK, {document['entry_count']} entries validated\n")
        return 0

    args.out.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    sys.stderr.write(f"generate-repair-map: wrote {document['entry_count']} entries to {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
