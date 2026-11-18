"""Unit tests for hooks/pretool-read-size-guard.py: the guard judges a Read by
the number of lines it actually returns (OB-L43).

The Read tool's `offset` is the 1-based line to start from and its `limit`
defaults to 2000 lines, so a Read returns min(limit or 2000, total - offset + 1)
lines. A Read of the tail of a large file that returns at most 600 lines passes;
a Read that returns more than 600 lines is still refused. A malformed offset
(0, negative, a bool, a string, a float) counts as reading from line 1 and so
never creates an allow.

Tests invoke the hook as a subprocess (the way the harness does) and assert the
exit code: 0 = allow, 2 = block. The root conftest gives every test a throwaway
HOME and state dir.
"""

import json
import os
import subprocess
import sys

import pytest

HOOK = os.path.join(os.path.dirname(__file__), '..', 'pretool-read-size-guard.py')


@pytest.fixture
def big_md(tmp_path):
    path = tmp_path / 'big.md'
    path.write_text(''.join(f'line {i}\n' for i in range(1, 651)))
    return str(path)


def _run(tool_input, cwd):
    env = dict(os.environ)
    for name in ('CLAUDE_TASK_ID', 'CLAUDE_SESSION_ID'):
        env.pop(name, None)
    payload = {'tool_name': 'Read', 'session_id': 'ob-l43-test', 'tool_input': tool_input}
    proc = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=str(cwd), timeout=30)
    return proc.returncode, proc.stderr


# --- the over-block being lifted ------------------------------------------

def test_tail_read_offset_600_no_limit_passes(big_md, tmp_path):
    """650-line file, offset 600, no limit: returns lines 600-650 (51 lines)."""
    rc, err = _run({'file_path': big_md, 'offset': 600}, tmp_path)
    assert rc == 0, err


@pytest.mark.parametrize('offset', [51, 100, 650, 700])
def test_offset_leaving_at_most_600_lines_passes(big_md, tmp_path, offset):
    rc, err = _run({'file_path': big_md, 'offset': offset}, tmp_path)
    assert rc == 0, err


def test_offset_with_oversized_limit_but_short_tail_passes(big_md, tmp_path):
    rc, err = _run({'file_path': big_md, 'offset': 600, 'limit': 2000}, tmp_path)
    assert rc == 0, err


# --- must still refuse -----------------------------------------------------

def test_no_limit_no_offset_refused(big_md, tmp_path):
    rc, err = _run({'file_path': big_md}, tmp_path)
    assert rc == 2
    assert '650 lines' in err


def test_limit_2000_refused(big_md, tmp_path):
    rc, _ = _run({'file_path': big_md, 'limit': 2000}, tmp_path)
    assert rc == 2


def test_offset_10_no_limit_returns_641_lines_refused(big_md, tmp_path):
    rc, _ = _run({'file_path': big_md, 'offset': 10}, tmp_path)
    assert rc == 2


def test_offset_50_no_limit_returns_601_lines_refused(big_md, tmp_path):
    rc, _ = _run({'file_path': big_md, 'offset': 50}, tmp_path)
    assert rc == 2


@pytest.mark.parametrize('offset', [0, -1, -600, True, '600', 600.0, None, [600], {'n': 600}])
def test_malformed_offset_never_allows(big_md, tmp_path, offset):
    rc, _ = _run({'file_path': big_md, 'offset': offset}, tmp_path)
    assert rc == 2


@pytest.mark.parametrize('limit', [0, -5, '100', 100.0, None])
def test_malformed_limit_with_small_offset_refused(big_md, tmp_path, limit):
    rc, _ = _run({'file_path': big_md, 'offset': 10, 'limit': limit}, tmp_path)
    assert rc == 2


# --- unchanged behaviour ---------------------------------------------------

def test_bounded_limit_still_passes(big_md, tmp_path):
    rc, err = _run({'file_path': big_md, 'offset': 1, 'limit': 600}, tmp_path)
    assert rc == 0, err
