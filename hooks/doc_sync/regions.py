#!/usr/bin/env python3
"""The one marker-region classifier every doc_sync consumer shares.

Four unrelated predicates used to decide what a file's AUTO region is (README first
occurrence, INDEX substring plus whole-line, section replacement first occurrence, the
CLAUDE.md per-section substring). They disagreed on prose mentions, fenced examples and
same-line pairs, so one caller could regenerate what another refused to classify. This
module is the single decision: a fence-aware, whole-line scan whose shapes are enumerated
and mapped to the statuses the callers report.

Stdlib-only leaf, on purpose: it imports no sibling module, so every other doc_sync module
(and the standalone-loaded regen_readme) can import it without a cycle, and the class
objects defined here (RegenStatus above all) exist exactly once per process.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, Optional

README_MARKER_ID = 'readme-stats'
INDEX_MARKER_ID = 'index-stats'


def marker_open(marker_id: str) -> str:
    return f'<!-- AUTO:{marker_id} -->'


def marker_close(marker_id: str) -> str:
    return f'<!-- /AUTO:{marker_id} -->'


class RegenStatus(str, Enum):
    """Outcome of a regeneration; every path returns one so a caller can tell a skip from a write."""
    WRITTEN = 'WRITTEN'
    SKIPPED_GITHUB_RESERVED = 'SKIPPED_GITHUB_RESERVED'
    SKIPPED_NO_OPENING_MARKER = 'SKIPPED_NO_OPENING_MARKER'
    SKIPPED_NO_CLOSING_MARKER = 'SKIPPED_NO_CLOSING_MARKER'
    SKIPPED_MALFORMED_MARKERS = 'SKIPPED_MALFORMED_MARKERS'


class RegionShape(str, Enum):
    """What the marker tokens of one id look like in a text (see the decision procedure below)."""
    WELL_FORMED = 'WELL_FORMED'
    NO_MARKERS = 'NO_MARKERS'
    ONLY_CLOSING = 'ONLY_CLOSING'
    ONLY_OPENING = 'ONLY_OPENING'
    REVERSED = 'REVERSED'
    DUPLICATE_OPENING = 'DUPLICATE_OPENING'
    DUPLICATE_CLOSING = 'DUPLICATE_CLOSING'
    MULTIPLE_REGIONS = 'MULTIPLE_REGIONS'
    NESTED_REGIONS = 'NESTED_REGIONS'
    FOREIGN_MARKER_INSIDE = 'FOREIGN_MARKER_INSIDE'
    NEAR_MISS_MARKER = 'NEAR_MISS_MARKER'
    UNCLOSED_FENCE = 'UNCLOSED_FENCE'
    # Replace-level shapes: the text was fine, the generated body would break it.
    BODY_CONTAINS_MARKER = 'BODY_CONTAINS_MARKER'
    BODY_BREAKS_REGION = 'BODY_BREAKS_REGION'


class ArtifactKind(str, Enum):
    README = 'README'
    INDEX = 'INDEX'
    CLAUDE_MD_SECTION = 'CLAUDE_MD_SECTION'


class RegenRecord(NamedTuple):
    """One skipped artifact, as the regeneration code hands it to the notice module."""
    kind: ArtifactKind
    path: object
    status: RegenStatus
    marker_id: Optional[str] = None
    shape: Optional[RegionShape] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class RegionResult:
    shape: RegionShape
    status: Optional[RegenStatus]
    open_line: Optional[int] = None
    close_line: Optional[int] = None
    fence_line: Optional[int] = None


@dataclass(frozen=True)
class ReplaceResult:
    text: str
    shape: RegionShape
    replaced: bool


# A missing or misplaced closing marker is the #83 status; a missing opening marker likewise.
# Every other non-well-formed shape is one status: the file needs a human, not a guess.
_STATUS_OF_SHAPE = {
    RegionShape.WELL_FORMED: None,
    RegionShape.NO_MARKERS: RegenStatus.SKIPPED_NO_OPENING_MARKER,
    RegionShape.ONLY_CLOSING: RegenStatus.SKIPPED_NO_OPENING_MARKER,
    RegionShape.ONLY_OPENING: RegenStatus.SKIPPED_NO_CLOSING_MARKER,
    RegionShape.REVERSED: RegenStatus.SKIPPED_NO_CLOSING_MARKER,
}

_BOM = chr(0xFEFF)  # spelled out, not a literal: an invisible character in the source is unreviewable
# Fence lines allow at most three leading spaces (four or a tab make indented code).
_FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
# A marker of any id in its exact spelling; the generated-content self-check uses it.
_ANY_MARKER_RE = re.compile(r'<!-- /?AUTO:[^\s>]+ -->\Z')
_NEAR_MISS_CACHE: dict = {}


def _near_miss_re(marker_id: str):
    """Marker-only line, one or two tokens, tolerant of case and inner spacing.

    Deliberately `(?:/\\s*)?` after a single `\\s*`: the obvious `/?\\s*` spelling puts two
    adjacent whitespace runs in the pattern and backtracks quadratically on long space runs.
    """
    compiled = _NEAR_MISS_CACHE.get(marker_id)
    if compiled is None:
        token = r'<!--\s*(?:/\s*)?AUTO:' + re.escape(marker_id) + r'\s*-->'
        compiled = re.compile(r'(?:' + token + r')(?:\s*' + token + r')?\Z', re.IGNORECASE)
        _NEAR_MISS_CACHE[marker_id] = compiled
    return compiled


def _match_line(raw: str, first: bool) -> str:
    """The line as the scanner sees it: no BOM on line 1, no trailing CR."""
    if first and raw.startswith(_BOM):
        raw = raw[1:]
    if raw.endswith('\r'):
        raw = raw[:-1]
    return raw


def _fence_run(match_line: str):
    """(fence char, run length, info string) when the line has fence shape, else None."""
    found = _FENCE_RE.match(match_line)
    if found is None:
        return None
    run = found.group(1)
    return run[0], len(run), found.group(2)


def classify_region(text: str, marker_id: str) -> RegionResult:
    """Classify the AUTO region of `marker_id` in `text`.

    Lines are split on newline only (a form feed or U+2028 is not a line break here). A marker
    line equals the exact marker text once spaces and tabs are stripped. Fenced code is
    skipped; containers (blockquote, list), HTML comments, front matter and indented code
    are not tracked. Decision procedure, first match wins:

    1. a marker line of this id hidden by a fence that never closes: UNCLOSED_FENCE
    2. a marker-only line that is not exact: NEAR_MISS_MARKER
    3. no tokens NO_MARKERS, no opening ONLY_CLOSING, no closing ONLY_OPENING,
       first token a closing marker REVERSED
    4. exactly [opening, closing]: FOREIGN_MARKER_INSIDE when another id's marker lies
       between them, else WELL_FORMED
    5. otherwise DUPLICATE_OPENING (one closing), DUPLICATE_CLOSING (one opening),
       NESTED_REGIONS (two openings before the first closing) or MULTIPLE_REGIONS
    """
    open_text = marker_open(marker_id)
    close_text = marker_close(marker_id)
    near_miss = _near_miss_re(marker_id)
    tokens = []          # (kind, 1-based line) outside fences
    foreign = []         # 1-based lines of other ids' exact markers outside fences
    has_near_miss = False
    fence = None         # (char, length, opener line) while inside a fenced block
    hidden = False       # a marker line of this id seen inside the currently open fence
    for number, raw in enumerate(text.split('\n'), start=1):
        line = _match_line(raw, number == 1)
        run = _fence_run(line)
        if fence is not None:
            if run and run[0] == fence[0] and run[1] >= fence[1] and not run[2].strip(' \t'):
                fence = None
                hidden = False
            elif line.strip(' \t') in (open_text, close_text):
                hidden = True
            continue
        if run and not (run[0] == '`' and '`' in run[2]):
            fence = (run[0], run[1], number)
            continue
        stripped = line.strip(' \t')
        if stripped == open_text:
            tokens.append(('O', number))
        elif stripped == close_text:
            tokens.append(('C', number))
        elif stripped.startswith('<!--'):
            if near_miss.match(stripped):
                has_near_miss = True
            elif _ANY_MARKER_RE.match(stripped):
                foreign.append(number)
    kinds = [kind for kind, _ in tokens]
    open_line = next((n for k, n in tokens if k == 'O'), None)
    close_line = next((n for k, n in tokens if k == 'C'), None)

    def result(shape, fence_line=None):
        return RegionResult(shape, _STATUS_OF_SHAPE.get(shape, RegenStatus.SKIPPED_MALFORMED_MARKERS),
                            open_line, close_line, fence_line)

    if fence is not None and hidden:
        return result(RegionShape.UNCLOSED_FENCE, fence_line=fence[2])
    if has_near_miss:
        return result(RegionShape.NEAR_MISS_MARKER)
    if not tokens:
        return result(RegionShape.NO_MARKERS)
    if 'O' not in kinds:
        return result(RegionShape.ONLY_CLOSING)
    if 'C' not in kinds:
        return result(RegionShape.ONLY_OPENING)
    if kinds[0] == 'C':
        return result(RegionShape.REVERSED)
    if kinds == ['O', 'C']:
        if any(open_line < number < close_line for number in foreign):
            return result(RegionShape.FOREIGN_MARKER_INSIDE)
        return result(RegionShape.WELL_FORMED)
    if kinds.count('C') == 1:
        return result(RegionShape.DUPLICATE_OPENING)
    if kinds.count('O') == 1:
        return result(RegionShape.DUPLICATE_CLOSING)
    if kinds[:kinds.index('C')].count('O') >= 2:
        return result(RegionShape.NESTED_REGIONS)
    return result(RegionShape.MULTIPLE_REGIONS)


def marker_line_numbers(text: str) -> list:
    """1-based numbers of lines that are, whole and exact, a marker of ANY id.

    The generated-content self-check uses this on a body about to be written: marker text
    of any id in it (fenced tree included) would let a later run misread the file, so the
    caller skips instead of writing.
    """
    found = []
    for number, raw in enumerate(text.split('\n'), start=1):
        stripped = _match_line(raw, number == 1).strip(' \t')
        if stripped.startswith('<!--') and _ANY_MARKER_RE.match(stripped):
            found.append(number)
    return found


def _splice(text: str, region: RegionResult, new_body: str) -> str:
    """Replace the lines between the marker lines; the marker lines stay byte for byte."""
    lines = text.split('\n')
    head = '\n'.join(lines[:region.open_line])
    tail = '\n'.join(lines[region.close_line - 1:])
    return head + '\n' + new_body + '\n' + tail


def replace_region(text: str, marker_id: str, new_body: str) -> ReplaceResult:
    """Replace the body of the well-formed region of `marker_id`; anything else is returned as is.

    The built result is classified again: a body that would leave the text malformed (marker
    lines of its own, a code fence that leaks past the closing marker, a near-miss line), or
    whose second application would change the text, is refused. That refusal is what keeps a
    body holding its own closing marker from growing the file on every run.
    """
    region = classify_region(text, marker_id)
    if region.shape is not RegionShape.WELL_FORMED:
        return ReplaceResult(text, region.shape, False)
    built = _splice(text, region, new_body)
    rebuilt = classify_region(built, marker_id)
    if rebuilt.shape is RegionShape.WELL_FORMED and _splice(built, rebuilt, new_body) == built:
        return ReplaceResult(built, RegionShape.WELL_FORMED, True)
    refused = (RegionShape.BODY_CONTAINS_MARKER if marker_line_numbers(new_body)
               else RegionShape.BODY_BREAKS_REGION)
    return ReplaceResult(text, refused, False)
