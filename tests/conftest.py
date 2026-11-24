"""A test that ends with its process changed fails by name.

A test runner process runs thousands of tests one after another, so what one leaves changed in the process (its
working directory, its file-mode mask, whether it adopts orphaned children) is what every later test meets. The
guard below checks these three after each test (the replay suite's own conftest does the same for a modeled
clock, and its tests are not covered here). A test that needs one of them changed puts it back itself: the
`monkeypatch` fixture for the directory, a module fixture that restores (see test_git_auto_push_opt_in.subreaper)
for the subreaper setting. hooks/tests/conftest.py uses this same fixture.
"""
from __future__ import annotations

import ctypes
import os

import pytest


def _process_state() -> dict:
    mask = os.umask(0o022)
    os.umask(mask)
    adopts = ctypes.c_int(-1)
    try:
        ctypes.CDLL(None, use_errno=True).prctl(37, ctypes.byref(adopts), 0, 0, 0)  # PR_GET_CHILD_SUBREAPER
    except (OSError, AttributeError):
        pass
    return {"working directory": os.getcwd(), "file-mode mask": oct(mask),
            "subreaper setting (adopts orphaned children)": adopts.value}


@pytest.fixture(autouse=True)
def process_state_guard(request):
    if "tests/replay/" in request.node.nodeid:
        yield
        return
    before = _process_state()
    yield
    after = _process_state()
    changed = [f"{name}: {before[name]!r} -> {after[name]!r}" for name in before if before[name] != after[name]]
    if changed:
        os.chdir(before["working directory"])
        os.umask(int(before["file-mode mask"], 8))
        ctypes.CDLL(None).prctl(36, max(before["subreaper setting (adopts orphaned children)"], 0), 0, 0, 0)
        pytest.fail(f"{request.node.nodeid} left its process changed ({'; '.join(changed)}); "
                    "put it back before the test ends (monkeypatch.chdir, a restoring fixture)", pytrace=False)
