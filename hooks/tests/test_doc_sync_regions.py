#!/usr/bin/env python3
"""Pure-function tests for hooks/doc_sync/regions.py, the one marker-region classifier.

Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
plus whole-line, section replacement first occurrence, CLAUDE.md per-section substring) are
replaced by one fence-aware, whole-line classifier whose shapes are enumerated. These tests
pin every shape, the scan corner cases, the replace contract and the import contract.

New symbols are reached through load(), inside the test node, never through a module-level
from-import: run against a tree that lacks the module, the tests fail one by one instead of
failing at collection. Modules are loaded only through importlib.import_module of the
package-name path (the package rebinds the attribute `main` to a function).

Isolation: nothing here touches the repository tree. The regenerating cases work in
tmp_path with HOME and TMPDIR redirected and the doc-sync environment scrubbed.
"""

import ast
import importlib
import importlib.util
import itertools
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_SYNC = REPO_ROOT / 'hooks' / 'doc_sync'
sys.path.insert(0, str(REPO_ROOT))

SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    scratch_tmp = tmp_path / 'tmp'
    home.mkdir()
    scratch_tmp.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('TMPDIR', str(scratch_tmp))
    for name in SCRUBBED_ENV:
        monkeypatch.delenv(name, raising=False)


def load(name):
    """hooks.doc_sync.<name>; a module that cannot be imported fails the calling test."""
    try:
        return importlib.import_module(f'hooks.doc_sync.{name}')
    except ImportError as error:
        pytest.fail(f'hooks.doc_sync.{name} cannot be imported: {error}')


O = '<!-- AUTO:x -->'
C = '<!-- /AUTO:x -->'
OY = '<!-- AUTO:y -->'
CY = '<!-- /AUTO:y -->'
OXY = '<!-- AUTO:x-y -->'
CXY = '<!-- /AUTO:x-y -->'


def t(*lines):
    return '\n'.join(lines) + '\n'


def classify(text, marker_id='x'):
    return load('regions').classify_region(text, marker_id)


def names(result):
    return result.shape.name, (result.status.name if result.status is not None else None)


BOM = chr(0xFEFF)  # spelled out: an escape or a literal here would be invisible in review
LS = chr(0x2028)
NO_OPENING = 'SKIPPED_NO_OPENING_MARKER'
NO_CLOSING = 'SKIPPED_NO_CLOSING_MARKER'
MALFORMED = 'SKIPPED_MALFORMED_MARKERS'

# (text, shape, status[, marker id]) rows per id of the ticket's shape table M-01..M-22.
SHAPE_CASES = {
    'cls_M01': [(t('head', O, 'body', C, 'tail'), 'WELL_FORMED', None)],
    'cls_M02': [(t(O, C), 'WELL_FORMED', None), (t('a', O, C, 'b'), 'WELL_FORMED', None)],
    'cls_M03': [(t('plain hand text'), 'NO_MARKERS', NO_OPENING)],
    'cls_M04': [(t('a', C, 'b'), 'ONLY_CLOSING', NO_OPENING)],
    'cls_M05': [(t('a', O, 'b'), 'ONLY_OPENING', NO_CLOSING)],
    'cls_M06': [(t(C, O), 'REVERSED', NO_CLOSING), (t(C, O, C), 'REVERSED', NO_CLOSING)],
    'cls_M07': [(t(O, O, C), 'DUPLICATE_OPENING', MALFORMED), (t(O, C, O), 'DUPLICATE_OPENING', MALFORMED)],
    'cls_M08': [(t(O, C, C), 'DUPLICATE_CLOSING', MALFORMED)],
    'cls_M09': [(t(O, C, O, C), 'MULTIPLE_REGIONS', MALFORMED)],
    'cls_M10': [(t(O, O, C, C), 'NESTED_REGIONS', MALFORMED)],
    'cls_M11': [(t(O, OY, 'z', CY, C), 'FOREIGN_MARKER_INSIDE', MALFORMED),
                (t(O, 'z', OY, C), 'FOREIGN_MARKER_INSIDE', MALFORMED)],
    'cls_M12': [(t('<!--AUTO:x-->'), 'NEAR_MISS_MARKER', MALFORMED),
                (t('<!-- auto:x -->'), 'NEAR_MISS_MARKER', MALFORMED),
                (t(O, '<!--  /AUTO:x  -->'), 'NEAR_MISS_MARKER', MALFORMED),
                (t(O, 'body', C, '<!-- AUTO:x  -->'), 'NEAR_MISS_MARKER', MALFORMED)],
    'cls_M13': [(t(f'{O} {C}'), 'NEAR_MISS_MARKER', MALFORMED), (t(f'{O}{C}'), 'NEAR_MISS_MARKER', MALFORMED),
                (t(O, C, f'{O} {C}'), 'NEAR_MISS_MARKER', MALFORMED),
                # An inline pair together with prose is no marker at all (near miss needs a line of
                # marker tokens only): pinned so the boundary is stated, not assumed.
                (t(f'text {O} {C} text'), 'NO_MARKERS', NO_OPENING),
                (t(f'{O} {C} trailing prose'), 'NO_MARKERS', NO_OPENING)],
    'cls_M14': [(t('```', O, C, '```'), 'NO_MARKERS', NO_OPENING),
                (t('```', O, 'x', '```', 'hand'), 'NO_MARKERS', NO_OPENING)],
    'cls_M15': [(t('```', O, 'example', C, '```', O, 'real', C), 'WELL_FORMED', None),
                (t(O, 'real', C, '```', O, C, '```'), 'WELL_FORMED', None)],
    'cls_M16': [(t(f'  {O}', 'body', f'  {C}'), 'WELL_FORMED', None), (t(f'\t{O}', 'body', f'\t{C}'), 'WELL_FORMED', None)],
    # M-17 is a replace-level shape; at classify level the text a naive splice would produce
    # (the body's own marker line inside the region) is malformed.
    'cls_M17': [(t(O, 'old', C, C), 'DUPLICATE_CLOSING', MALFORMED), (t(O, O, C), 'DUPLICATE_OPENING', MALFORMED)],
    'cls_M18': [(t(O, 'a', C, OXY, 'b', CXY), 'WELL_FORMED', None),
                (t(O, 'a', C, OXY, 'b', CXY), 'WELL_FORMED', None, 'x-y'),
                (t(OXY, 'b', CXY), 'NO_MARKERS', NO_OPENING),
                (t(O, 'a', C), 'NO_MARKERS', NO_OPENING, 'x-y')],
    'cls_M21': [('', 'NO_MARKERS', NO_OPENING)],
    'cls_M22': [(t(O, 'body', C).replace('\n', '\r\n'), 'WELL_FORMED', None),
                (t(C, O).replace('\n', '\r\n'), 'REVERSED', NO_CLOSING)],
}


@pytest.mark.parametrize('cases', [pytest.param(cases, id=token) for token, cases in SHAPE_CASES.items()])
def test_classify_matrix_shape_table(cases):
    """Every row of the ticket's shape table classifies to its shape and status."""
    for row in cases:
        text, shape, status = row[:3]
        marker_id = row[3] if len(row) > 3 else 'x'
        assert names(classify(text, marker_id)) == (shape, status), (text, marker_id)


def test_classify_matrix_status_is_none_exactly_when_well_formed():
    """The status is None only for WELL_FORMED, for every row of the table."""
    for cases in SHAPE_CASES.values():
        for row in cases:
            result = classify(row[0], row[3] if len(row) > 3 else 'x')
            assert (result.status is None) == (result.shape.name == 'WELL_FORMED')


def test_classify_matrix_cls_unclosed_fence_hides_pair():
    """A fence that never closes hides the pair: UNCLOSED_FENCE with the opener's line."""
    result = classify(t('intro', '```', O, 'body', C))
    assert names(result) == ('UNCLOSED_FENCE', MALFORMED)
    assert result.fence_line == 2
    # A real pair before the fence does not save it once a marker line sits inside the open fence.
    assert names(classify(t(O, C, '```', O, C)))[0] == 'UNCLOSED_FENCE'
    # An unclosed fence that hides no marker of this id is harmless.
    assert names(classify(t(O, C, '```', 'code'))) == ('WELL_FORMED', None)
    # Three leading spaces still open a fence; four make indented code.
    assert names(classify(t('   ```', O, C)))[0] == 'UNCLOSED_FENCE'


def test_classify_matrix_cls_four_backtick_outer_fence():
    """A three-backtick line inside a four-backtick fence does not close it."""
    assert names(classify(t('````', '```', O, C, '```', '````'))) == ('NO_MARKERS', NO_OPENING)
    assert names(classify(t('````', '```', O, C, '```', '````', O, 'real', C))) == ('WELL_FORMED', None)
    # A longer closing run closes; a shorter one leaves the fence open.
    assert names(classify(t('```', O, C, '````', O, 'r', C))) == ('WELL_FORMED', None)
    assert names(classify(t('````', O, C, '```', O, 'r', C)))[0] == 'UNCLOSED_FENCE'


def test_classify_matrix_cls_tilde_fence():
    """Tilde fences work like backtick fences and only a tilde run closes them."""
    assert names(classify(t('~~~', O, C, '~~~', O, 'real', C))) == ('WELL_FORMED', None)
    assert names(classify(t('~~~', '```', O, C, '```', '~~~'))) == ('NO_MARKERS', NO_OPENING)
    assert names(classify(t('~~~', O, C, '```')))[0] == 'UNCLOSED_FENCE'


def test_classify_matrix_cls_backtick_info_string_not_fence():
    """A backtick line whose info string holds a backtick is not a fence; a tilde one may."""
    assert names(classify(t('``` a`b', O, 'body', C))) == ('WELL_FORMED', None)
    assert names(classify(t('~~~ a`b', O, C, '~~~', O, 'r', C))) == ('WELL_FORMED', None)


def test_classify_matrix_cls_indent_four_not_fence():
    """Four leading spaces make indented code, not a fence, so the pair below is not hidden."""
    assert names(classify(t('    ```', O, 'body', C))) == ('WELL_FORMED', None)
    assert names(classify(t('\t```', O, 'body', C))) == ('WELL_FORMED', None)


def test_classify_matrix_cls_bom_line_one():
    """A byte order mark on line 1 is dropped for matching only."""
    assert names(classify(BOM + t(O, 'body', C))) == ('WELL_FORMED', None)
    # On a later line it is ordinary text, so the line is not a marker.
    assert names(classify(t('head', BOM + O, 'body', C)))[0] == 'ONLY_CLOSING'


def test_classify_matrix_cls_crlf_equals_lf():
    """CRLF and LF classify identically for every row of the table."""
    for cases in SHAPE_CASES.values():
        for row in cases:
            marker_id = row[3] if len(row) > 3 else 'x'
            lf = row[0].replace('\r\n', '\n')
            crlf = lf.replace('\n', '\r\n')
            assert names(classify(lf, marker_id)) == names(classify(crlf, marker_id))
    assert classify(t('```', O, C).replace('\n', '\r\n')).fence_line == 1


def test_classify_matrix_cls_trailing_space_tab():
    """Trailing spaces and tabs are ignored; interior spacing changes make a near miss."""
    assert names(classify(t(O + ' \t ', 'body', C + '\t'))) == ('WELL_FORMED', None)
    assert names(classify(t('<!-- AUTO:x\t-->')))[0] == 'NEAR_MISS_MARKER'


def test_classify_matrix_cls_tab_indented():
    """Tab and space indentation of a marker line still count as that marker."""
    assert names(classify(t('\t' + O, 'body', ' \t' + C))) == ('WELL_FORMED', None)


def test_classify_matrix_cls_blockquote_not_marker():
    """A marker inside a blockquote is prose: no marker, and not a near miss either."""
    assert names(classify(t('> ' + O, '> body', '> ' + C))) == ('NO_MARKERS', NO_OPENING)
    assert names(classify(t('>' + O)))[0] == 'NO_MARKERS'


def test_classify_matrix_cls_list_item_not_marker():
    """A marker inside a list item is prose: no marker, and not a near miss either."""
    for prefix in ('- ', '* ', '1. '):
        assert names(classify(t(prefix + O, prefix + C))) == ('NO_MARKERS', NO_OPENING)


def test_classify_matrix_cls_multiline_html_comment_not_tracked():
    """Containers are not tracked (pinned): a pair inside a multi-line HTML comment counts."""
    assert names(classify(t('<!--', O, 'body', C, '-->'))) == ('WELL_FORMED', None)


def test_classify_matrix_cls_front_matter_not_tracked():
    """Front matter is not tracked (pinned): a pair inside it counts."""
    assert names(classify(t('---', O, 'body', C, '---', 'text'))) == ('WELL_FORMED', None)


def test_classify_matrix_cls_foreign_marker_inside():
    """Another id's whole-line marker between the pair makes it FOREIGN_MARKER_INSIDE."""
    assert names(classify(t(O, OY, 'z', CY, C))) == ('FOREIGN_MARKER_INSIDE', MALFORMED)
    # Outside the pair, or inside a fence between the pair, a foreign marker does not matter.
    assert names(classify(t(OY, 'z', CY, O, 'b', C))) == ('WELL_FORMED', None)
    assert names(classify(t(O, '```', OY, '```', C))) == ('WELL_FORMED', None)
    # A whole-line marker is exact: an inline mention of another id is prose.
    assert names(classify(t(O, f'see {OY} here', C))) == ('WELL_FORMED', None)


def oracle_shape(kinds):
    """Independent restatement of the decision procedure over a token sequence (no fences)."""
    if not kinds:
        return 'NO_MARKERS'
    if 'O' not in kinds:
        return 'ONLY_CLOSING'
    if 'C' not in kinds:
        return 'ONLY_OPENING'
    if kinds[0] == 'C':
        return 'REVERSED'
    if kinds == ['O', 'C']:
        return 'WELL_FORMED'
    if kinds.count('C') == 1:
        return 'DUPLICATE_OPENING'
    if kinds.count('O') == 1:
        return 'DUPLICATE_CLOSING'
    return 'NESTED_REGIONS' if kinds[:kinds.index('C')].count('O') >= 2 else 'MULTIPLE_REGIONS'


def test_classify_matrix_cls_exhaustive_sequences_len6():
    """Every opening/closing sequence up to length six matches the decision procedure."""
    total = 0
    for length in range(0, 7):
        for kinds in itertools.product('OC', repeat=length):
            kinds = list(kinds)
            text = ''.join((O if kind == 'O' else C) + '\n' for kind in kinds)
            expected = oracle_shape(kinds)
            result = classify(text)
            assert result.shape.name == expected, kinds
            status = {'WELL_FORMED': None, 'NO_MARKERS': NO_OPENING, 'ONLY_CLOSING': NO_OPENING,
                      'ONLY_OPENING': NO_CLOSING, 'REVERSED': NO_CLOSING}.get(expected, MALFORMED)
            assert (result.status.name if result.status else None) == status, kinds
            total += 1
    assert total == sum(2 ** n for n in range(7)) == 127


def test_classify_matrix_cls_near_miss_linear_time():
    """Long runs of spaces inside a marker-shaped line are classified in linear time."""
    for size in (2000, 8000, 32000):
        pad = ' ' * size
        lines = [
            '<!--' + pad + '/' + pad + 'AUTO:x' + pad,
            '<!--' + pad + 'AUTO:x' + pad + '-->' + pad + '!',
            '<!--' + pad + 'AUTO:x' + pad + '-->' + pad + '<!--' + pad,
        ]
        for line in lines:
            started = time.perf_counter()
            result = classify(t(line))
            elapsed = time.perf_counter() - started
            assert elapsed < 0.1, (size, elapsed)
            assert result.shape.name == 'NO_MARKERS'
    # The linear pattern still finds the real near misses with generous spacing.
    assert names(classify(t('<!--' + ' ' * 5000 + 'AUTO:x' + ' ' * 5000 + '-->')))[0] == 'NEAR_MISS_MARKER'


def test_classify_matrix_cls_near_miss_prose_never():
    """A mention inside prose is never a near miss; a line of marker tokens alone is."""
    prose = [
        f'see {O} for details', f'{O} is the opening marker', f'use {O} and {C} around the block',
        f'text {O} {C} text',            # inline pair together with prose: no marker at all
        f'- `name` - {O}', f'├── `f.py` - {O}', f'`{O}`', f'<!--AUTO:x--> trailing prose',
        f'{O} {C} {O}',                  # three tokens on one line are not "one or two"
    ]
    for line in prose:
        assert names(classify(t(line))) == ('NO_MARKERS', NO_OPENING), line
    # Only a line made up solely of one or two marker tokens is a near miss.
    for line in (f'{O} {C}', f'{O}{C}', '<!--AUTO:x-->', f'{O} {O}', f'  {O}   {C}  '):
        assert names(classify(t(line))) == ('NEAR_MISS_MARKER', MALFORMED), line


def test_classify_matrix_cls_generated_body_lines_never_near_miss():
    """Lines a generator emits (list items, tree connectors, indented tree lines) never lock a file."""
    body_lines = [
        f'- `tool.py` - {O}', f'- `tool.py` - {C}', f'- `tool.py` - {O} {C}',
        f'├── `tool.py` - {O}', f'└── `tool.py` - {C}',
        f'│   ├── `tool.py` - {O} {C}', f'    └── `t.py` - <!--AUTO:x-->',
        f'- **Total files**: {O}',
    ]
    for line in body_lines:
        text = t(O, line, C)
        assert names(classify(text)) == ('WELL_FORMED', None), line


def test_classify_matrix_marker_line_numbers_finds_any_id():
    """The generated-content scan sees a whole-line marker of any id, fenced or not."""
    regions = load('regions')
    body = t('a', OY, '```', C, '```', f'inline {O}', f'\t{CXY}', '<!--AUTO:x-->')
    assert regions.marker_line_numbers(body) == [2, 4, 7]
    assert regions.marker_line_numbers(t('plain', '- `f` - text')) == []


def test_classify_matrix_result_lines_are_one_based():
    """open_line, close_line and fence_line are 1-based and None when absent."""
    result = classify(t('a', 'b', O, 'c', C))
    assert (result.open_line, result.close_line, result.fence_line) == (3, 5, None)
    assert classify(t('a')).open_line is None


REPLACE_SKIP_TEXTS = {
    'rep_skip_M03': t('plain'),
    'rep_skip_M04': t('a', C),
    'rep_skip_M05': t('a', O, 'stale'),
    'rep_skip_M06': t(C, 'mid', O, 'stale'),
    'rep_skip_M07': t(O, O, 'x', C),
    'rep_skip_M08': t(O, 'x', C, C),
    'rep_skip_M09': t(O, C, O, C),
    'rep_skip_M10': t(O, O, C, C),
    'rep_skip_M11': t(O, OY, C),
    'rep_skip_M12': t('<!--AUTO:x-->', 'b'),
    'rep_skip_M13': t(f'{O} {C}'),
    'rep_skip_M14': t('```', O, C, '```'),
}


@pytest.mark.parametrize('text', [pytest.param(text, id=token) for token, text in REPLACE_SKIP_TEXTS.items()])
def test_replace_matrix_skip_shapes_return_the_input(text):
    """Every skip shape comes back unchanged with replaced False and the classifier's shape."""
    regions = load('regions')
    result = regions.replace_region(text, 'x', 'NEW')
    assert result.text == text and result.replaced is False
    assert result.shape is regions.classify_region(text, 'x').shape


IDEMPOTENT_TEXTS = {
    'rep_idem_M01': t('head', O, 'old', C, 'tail'),
    'rep_idem_M02': t(O, C),
    'rep_idem_M15': t('```', O, 'example', C, '```', O, 'old', C, 'tail'),
    'rep_idem_M16': t(f'  {O}', 'old', f'\t{C}', 'tail'),
    'rep_idem_M22': t('head', O, 'old', C, 'tail').replace('\n', '\r\n'),
}


@pytest.mark.parametrize('text', [pytest.param(text, id=token) for token, text in IDEMPOTENT_TEXTS.items()])
def test_replace_matrix_well_formed_shapes_are_idempotent(text):
    """A well-formed text is replaced, and a second application with the same body is a no-op."""
    regions = load('regions')
    first = regions.replace_region(text, 'x', 'BODY 1\nBODY 2')
    second = regions.replace_region(first.text, 'x', 'BODY 1\nBODY 2')
    assert first.replaced is True and first.shape is regions.RegionShape.WELL_FORMED
    assert 'BODY 1\nBODY 2' in first.text and 'old' not in first.text
    assert second.text == first.text and second.replaced is True
    assert regions.classify_region(first.text, 'x').shape is regions.RegionShape.WELL_FORMED


def test_replace_matrix_rep_fence_verbatim_M15():
    """The fenced example (markers inside a closed fence) is kept byte for byte."""
    regions = load('regions')
    text = t('intro', '```md', O, 'example body', C, '```', 'between', O, 'old', C, 'tail')
    result = regions.replace_region(text, 'x', 'NEW')
    assert result.replaced
    assert result.text == t('intro', '```md', O, 'example body', C, '```', 'between', O, 'NEW', C, 'tail')


def test_replace_matrix_rep_indent_verbatim_M16():
    """Indented marker lines, with their exact indentation and trailing spaces, stay as written."""
    regions = load('regions')
    text = t('head', f'  {O} ', 'old', f'\t{C}\t', 'tail')
    result = regions.replace_region(text, 'x', 'NEW')
    assert result.text == t('head', f'  {O} ', 'NEW', f'\t{C}\t', 'tail')


def test_replace_matrix_rep_body_marker_open_M17():
    """A body that holds an opening marker line is refused: BODY_CONTAINS_MARKER, no growth."""
    regions = load('regions')
    text = t('head', O, 'old', C, 'tail')
    result = regions.replace_region(text, 'x', f'a\n{O}\nb')
    assert (result.text, result.replaced, result.shape.name) == (text, False, 'BODY_CONTAINS_MARKER')


def test_replace_matrix_rep_body_marker_close_M17():
    """A body that holds its own closing marker line no longer grows the file every run."""
    regions = load('regions')
    text = t('head', O, 'old', C, 'tail')
    sizes = []
    for _ in range(4):
        result = regions.replace_region(text, 'x', f'a\n{C}\nb')
        assert (result.replaced, result.shape.name) == (False, 'BODY_CONTAINS_MARKER')
        text = result.text
        sizes.append(len(text))
    assert len(set(sizes)) == 1
    # A foreign id's whole-line marker in the body is refused as well.
    assert regions.replace_region(text, 'x', f'a\n{OY}\nb').shape.name == 'BODY_CONTAINS_MARKER'


def test_replace_matrix_rep_body_fence_leak():
    """A body with an unbalanced code fence would swallow the closing marker: refused."""
    regions = load('regions')
    text = t('head', O, 'old', C, 'tail')
    result = regions.replace_region(text, 'x', '```\ncode')
    assert (result.text, result.replaced, result.shape.name) == (text, False, 'BODY_BREAKS_REGION')


def test_replace_matrix_rep_body_near_miss():
    """A body line that looks like a marker makes the result malformed: refused."""
    regions = load('regions')
    text = t('head', O, 'old', C, 'tail')
    for body in ('<!--AUTO:x-->', f'{O} {C}', '<!-- auto:x -->'):
        result = regions.replace_region(text, 'x', 'ok\n' + body)
        assert (result.text, result.replaced, result.shape.name) == (text, False, 'BODY_BREAKS_REGION'), body


def test_replace_matrix_rep_reclassify_property():
    """Whenever a region was replaced, the result classifies well-formed and re-applying is a no-op."""
    regions = load('regions')
    texts = [t(O, C), t('a', O, 'b', C, 'c'), t('```', O, C, '```', O, 'x', C), t(f' {O}', C).replace('\n', '\r\n')]
    bodies = ['', 'one', 'one\ntwo', '```\nfenced\n```', f'- `f` - {O}', 'ok\n' + O, '```\nopen', '<!--AUTO:x-->', '\n\n']
    for text in texts:
        for body in bodies:
            first = regions.replace_region(text, 'x', body)
            if first.replaced:
                assert regions.classify_region(first.text, 'x').shape is regions.RegionShape.WELL_FORMED, body
                again = regions.replace_region(first.text, 'x', body)
                assert again.text == first.text, body
            else:
                assert first.text == text and first.shape.name.startswith('BODY_'), body


def test_replace_matrix_rep_empty_body_M02():
    """An empty body is pinned as `opening`, one empty line, `closing`, and stays that way."""
    regions = load('regions')
    for text in (t(O, C), t(O, 'old', C), t(O, '', C)):
        result = regions.replace_region(text, 'x', '')
        assert result.text == t(O, '', C)
        assert regions.replace_region(result.text, 'x', '').text == result.text


def test_replace_matrix_rep_outside_region_bytes_identical():
    """Every byte before the opening marker line and after the closing one is unchanged."""
    regions = load('regions')
    head = 'H' + LS + 'ead\x0c\n\n  hand \t\n'
    tail = '\ntail \x85 text\r\nno final newline'
    text = f'{head}{O}\nold\n{C}{tail}'
    result = regions.replace_region(text, 'x', 'NEW')
    assert result.text == f'{head}{O}\nNEW\n{C}{tail}'
    assert result.text.startswith(head + O) and result.text.endswith(C + tail)


def test_replace_matrix_rep_section_wrapper_returns_str():
    """patch._replace_section stays a str-returning wrapper over replace_region."""
    regions = load('regions')
    patch = load('patch')
    text = t('head', O, 'old', C, 'tail')
    assert isinstance(patch._replace_section(text, 'x', 'NEW'), str)
    assert patch._replace_section(text, 'x', 'NEW') == regions.replace_region(text, 'x', 'NEW').text
    assert patch._replace_section(t('plain'), 'x', 'NEW') == t('plain')
    assert patch._replace_section(text, 'x', f'{C}') == text


def parse_module(name):
    return ast.parse((DOC_SYNC / f'{name}.py').read_text(), filename=f'{name}.py')


def imported_roots(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split('.')[0])
    return roots


def test_import_contract_imp_regions_stdlib_leaf():
    """regions.py imports only enum, re, dataclasses, typing and __future__."""
    assert imported_roots(parse_module('regions')) <= {'enum', 're', 'dataclasses', 'typing', '__future__'}


def test_import_contract_imp_no_relative_import_in_regions():
    """regions.py has no relative import at all (it is a leaf every other module can load)."""
    relative = [node for node in ast.walk(parse_module('regions'))
                if isinstance(node, ast.ImportFrom) and node.level > 0]
    assert relative == []


def test_import_contract_imp_identity_regen_readme_regions_notice():
    """RegenStatus is one class object in regions, regen_readme and notice."""
    regions, regen_readme, notice = load('regions'), load('regen_readme'), load('notice')
    assert regen_readme.RegenStatus is regions.RegenStatus
    assert notice.RegenStatus is regions.RegenStatus
    assert load('regen_index').RegenStatus is regions.RegenStatus


def test_import_contract_imp_keep_stable_names():
    """The names other code and the existing tests rely on still exist."""
    expected = {
        'regen_readme': ['RegenStatus', 'regen_readme', '_readme_needs_update', 'README_OPEN_MARKER',
                         'README_CLOSE_MARKER', 'README_MARKER_ID', 'SKIP_NAMES', 'SKIP_PREFIXES',
                         '_is_skipped', '_list_files', '_build_stats', '_skip_status'],
        'patch': ['_replace_section', 'patch_claude_md', 'datetime'],
        'main': ['main', 'patch_claude_md', '_maybe_regen_global', 'process_parent_dirs', '_regen_if_dir'],
        'notice': ['_readme_digest', 'write_state', 'STATE_ROOT_ENV', 'MAX_NOTICE_CHARS',
                   'STATE_FILE_TEMPLATE', 'emit_post_tool_notice'],
        'regen_index': ['AUTO_START', 'AUTO_END', 'regen_index', '_index_needs_update', 'datetime'],
    }
    for module_name, symbols in expected.items():
        module = importlib.import_module(f'hooks.doc_sync.{module_name}')
        missing = [symbol for symbol in symbols if not hasattr(module, symbol)]
        assert missing == [], (module_name, missing)
    regen_readme = load('regen_readme')
    assert regen_readme.README_OPEN_MARKER == '<!-- AUTO:readme-stats -->'
    assert regen_readme.README_CLOSE_MARKER == '<!-- /AUTO:readme-stats -->'
    assert regen_readme.README_MARKER_ID == 'readme-stats'
    assert load('regen_index').AUTO_START == '<!-- AUTO:index-stats -->'
    assert load('notice').STATE_ROOT_ENV == 'CLAUDE_DOC_SYNC_STATE_ROOT'
    assert load('notice').MAX_NOTICE_CHARS == 2000
    assert load('notice').STATE_FILE_TEMPLATE == 'doc-sync-notices-{audience}.json'


def load_bare_regen_readme():
    spec = importlib.util.spec_from_file_location('regen_readme_bare_under_test', DOC_SYNC / 'regen_readme.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_contract_imp_bare_standalone_regen_readme_written(tmp_path):
    """A bare-loaded regen_readme shares the RegenStatus class and writes a fresh and a managed README."""
    regions = load('regions')
    module = load_bare_regen_readme()
    assert not module.__package__
    assert module.RegenStatus is regions.RegenStatus
    directory = tmp_path / 'folder'
    directory.mkdir()
    (directory / 'a.py').write_text('"""A."""\n')
    assert module.regen_readme(directory, tmp_path) is regions.RegenStatus.WRITTEN
    assert module.regen_readme(directory, tmp_path) is regions.RegenStatus.WRITTEN


def test_import_contract_imp_bare_standalone_regen_readme_skip(tmp_path):
    """A bare-loaded regen_readme reports the skips with the shared status objects and writes nothing."""
    regions = load('regions')
    module = load_bare_regen_readme()
    cases = {
        'open': (f'# t\n\n{regions.marker_open("readme-stats")}\nstale\n', regions.RegenStatus.SKIPPED_NO_CLOSING_MARKER),
        'none': ('# t\n\nhand\n', regions.RegenStatus.SKIPPED_NO_OPENING_MARKER),
        'dup': (t(*([regions.marker_open('readme-stats')] * 2), regions.marker_close('readme-stats')),
                regions.RegenStatus.SKIPPED_MALFORMED_MARKERS),
    }
    for name, (text, status) in cases.items():
        directory = tmp_path / name
        directory.mkdir()
        (directory / 'README.md').write_text(text)
        assert module.regen_readme(directory, tmp_path) is status
        assert (directory / 'README.md').read_text() == text


def run_fresh(code, cwd, extra_path=None):
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED_ENV}
    env.update(PYTHONDONTWRITEBYTECODE='1', HOME=str(cwd), TMPDIR=str(cwd))
    if extra_path is not None:
        env['PYTHONPATH'] = str(extra_path)
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env,
                          cwd=str(cwd), timeout=60)


MODULES = ['main', 'regions', 'notice', 'patch', 'regen_index', 'regen_readme']


def test_import_contract_imp_fresh_process_package_name(tmp_path):
    """Every doc_sync module imports under the package name in a fresh process."""
    code = ('import importlib\n'
            f'for name in {MODULES!r}:\n'
            '    importlib.import_module("hooks.doc_sync." + name)\n'
            'from hooks.doc_sync import regions, regen_readme\n'
            'assert regen_readme.RegenStatus is regions.RegenStatus\n'
            'print("IMPORT-OK")')
    completed = run_fresh(code, tmp_path, extra_path=REPO_ROOT)
    assert completed.stdout.strip() == 'IMPORT-OK', completed.stderr


def test_import_contract_imp_fresh_process_production_name(tmp_path):
    """Every doc_sync module imports under the production name (hooks/ on the path) in a fresh process."""
    code = ('import importlib\n'
            f'for name in {MODULES!r}:\n'
            '    importlib.import_module("doc_sync." + name)\n'
            'from doc_sync import regions, notice\n'
            'assert notice.RegenStatus is regions.RegenStatus\n'
            'print("IMPORT-OK")')
    completed = run_fresh(code, tmp_path, extra_path=REPO_ROOT / 'hooks')
    assert completed.stdout.strip() == 'IMPORT-OK', completed.stderr


def imports_regions(name):
    """True when the module imports regions, relatively or through the standalone shim."""
    for node in ast.walk(parse_module(name)):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == 'regions':
            return True
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'import_module':
            if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'hooks.doc_sync.regions':
                return True
    return False


def test_import_contract_imp_dag_consumers_import_regions():
    """regen_readme, regen_index, patch and notice all consume regions (one classifier)."""
    assert [name for name in ('regen_readme', 'regen_index', 'patch', 'notice') if not imports_regions(name)] == []
    # regions never imports back: the module graph stays a DAG with regions as the leaf.
    assert imported_roots(parse_module('regions')).isdisjoint({'hooks', 'doc_sync', 'patch', 'notice'})


def test_import_contract_imp_regenstatus_five_members():
    """RegenStatus keeps its four names and values and gains exactly SKIPPED_MALFORMED_MARKERS."""
    status = load('regions').RegenStatus
    assert [(member.name, member.value) for member in status] == [
        ('WRITTEN', 'WRITTEN'),
        ('SKIPPED_GITHUB_RESERVED', 'SKIPPED_GITHUB_RESERVED'),
        ('SKIPPED_NO_OPENING_MARKER', 'SKIPPED_NO_OPENING_MARKER'),
        ('SKIPPED_NO_CLOSING_MARKER', 'SKIPPED_NO_CLOSING_MARKER'),
        ('SKIPPED_MALFORMED_MARKERS', 'SKIPPED_MALFORMED_MARKERS'),
    ]
