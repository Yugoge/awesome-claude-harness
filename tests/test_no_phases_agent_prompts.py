"""Every agent carries the two charter lines as one text, so the copies cannot drift apart.

Each agents/*.md (README and INDEX excepted) holds exactly one line starting "**Requirement baseline (charter" and one
starting "**Scope authority (charter", and every agent's line is the same.

This file used to also grep agents/ba.md, spec.md, dev.md, qa.md and agents/shared/no-phases.md for the owner's
no-phases ruling (D33) and the QA fail conditions that carry it. No hook, script or replay reads those sentences: the
QA that fails a phased plan is a model, so those greps were deleted (P15-L8). The ruling lives in prompt text only
(agents/shared/no-phases.md and the lines that point at it). Its one code consumer, the replay /spec driver's
split-QA check, is run by tests/test_no_phases_spec_command.py.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / "agents"
CHARTER = ("**Requirement baseline (charter", "**Scope authority (charter")


def _agent_files():
    return sorted(p for p in AGENTS.glob("*.md") if p.name not in ("README.md", "INDEX.md"))


def test_the_charter_lines_are_one_text_in_every_agent():
    seen = {key: {} for key in CHARTER}
    for path in _agent_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for key in CHARTER:
            found = [l for l in lines if l.startswith(key)]
            assert len(found) == 1, f"{path.name} must carry exactly one line starting {key}"
            seen[key].setdefault(found[0], []).append(path.name)
    for key, variants in seen.items():
        assert len(variants) == 1, f"{key}) differs between agents: " + "; ".join(
            f"{names[:3]}" for names in variants.values())
