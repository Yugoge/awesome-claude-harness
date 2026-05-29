"""
test_AC12_ac12-command-coverage.py

Verifies that the graphify dual-touchpoint integration is present in the
correct command files, and that graphify is explicitly disabled in commands/clean.md.

AC12: Command Coverage (spec-20260527-061433)
"""

import pytest
from pathlib import Path

PROJECT_DIR = Path(__file__).parents[3]


def test_AC12_dev_md_contains_graphify_query():
    """commands/dev.md references graphify-query.py (pre-BA hydrator touchpoint)."""
    dev_md = (PROJECT_DIR / "commands/dev.md").read_text(encoding="utf-8")
    assert "graphify-query.py" in dev_md, (
        "commands/dev.md must reference graphify-query.py for the pre-BA Bash hydrator"
    )


def test_AC12_dev_md_contains_graphify_enrich():
    """commands/dev.md references graphify-enrich.py (post-BA enrichment touchpoint)."""
    dev_md = (PROJECT_DIR / "commands/dev.md").read_text(encoding="utf-8")
    assert "graphify-enrich.py" in dev_md, (
        "commands/dev.md must reference graphify-enrich.py for the graphify enrichment subagent dispatch"
    )


def test_AC12_redev_md_references_graphify():
    """commands/redev.md references graphify integration."""
    redev_md = (PROJECT_DIR / "commands/redev.md").read_text(encoding="utf-8")
    assert "graphify" in redev_md, (
        "commands/redev.md must reference graphify (inherits /dev dual-touchpoint integration)"
    )


def test_AC12_pull_md_contains_graphify_maintain():
    """commands/pull.md contains graphify-maintain.py post-pull update trigger."""
    pull_md = (PROJECT_DIR / "commands/pull.md").read_text(encoding="utf-8")
    assert "graphify-maintain.py" in pull_md, (
        "commands/pull.md must reference graphify-maintain.py for the post-pull cache update"
    )


def test_AC12_clean_md_explicitly_disables_graphify():
    """commands/clean.md explicitly disables graphify."""
    clean_md = (PROJECT_DIR / "commands/clean.md").read_text(encoding="utf-8")
    graphify_lower = clean_md.lower()
    # The file must mention graphify AND indicate it is disabled
    assert "graphify" in graphify_lower, (
        "commands/clean.md must mention graphify to document its disabled status"
    )
    # Check for disabled/disable keyword near graphify context
    import re
    # Find all occurrences of "graphify" and check nearby context for "disabled"/"disable"
    matches = list(re.finditer(r"graphify", graphify_lower))
    assert any(
        "disabled" in graphify_lower[max(0, m.start() - 200):m.end() + 200]
        for m in matches
    ), (
        "commands/clean.md must explicitly indicate graphify is disabled "
        "(expected 'disabled' near 'graphify' context)"
    )


def test_AC12_dev_overnight_md_contains_graphify():
    """commands/dev-overnight.md contains graphify in sentinel fanout."""
    overnight_path = PROJECT_DIR / "commands/dev-overnight.md"
    if not overnight_path.exists():
        pytest.skip("commands/dev-overnight.md does not exist")
    overnight_md = overnight_path.read_text(encoding="utf-8")
    assert "graphify" in overnight_md, (
        "commands/dev-overnight.md must reference graphify in its sentinel fanout"
    )
