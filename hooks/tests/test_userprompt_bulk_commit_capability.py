"""Tests for hooks/userprompt-bulk-commit-capability.py's /commit --bulk detector.

These assertions (AC-FRESH-F-14) came from the tests of an unreachable script
deleted under D17; they cover the live hook only.
"""
import importlib.util
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "userprompt-bulk-commit-capability.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load(HOOK, "userprompt_bulk_commit_capability")


def test_bulk_commit_prompt_is_detected():
    assert hook._is_bulk_commit("/commit parent --bulk")


def test_close_fix_confirmation_prompt_is_not_a_bulk_commit():
    assert not hook._is_bulk_commit("/close parent --fix --confirm " + "a" * 32)
