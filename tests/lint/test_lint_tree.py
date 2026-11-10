"""The six lint checks on this repository's tree: one test each, no finding allowed.

Collected only under HARNESS_LINT=1, which the baseline workflow's lint step sets; the
ordinary suite skips them, so the step can stay off until the P12 lanes that clear today's
findings have landed. `python3 -m tests.lint` prints the same findings.
"""
from __future__ import annotations

import os

import pytest

from tests.lint.checks import CHECKS
from tests.lint.tree import REPO, Tree

pytestmark = pytest.mark.skipif(os.environ.get("HARNESS_LINT") != "1",
                                reason="the lint CI step runs these (HARNESS_LINT=1)")

TREE = Tree(REPO)


@pytest.mark.parametrize("name", list(CHECKS))
def test_tree_has_no_findings(name):
    findings = CHECKS[name](TREE)
    assert not findings, f"{len(findings)} {name} finding(s):\n" + "\n".join(f.text() for f in findings)
