"""Dispatches loaded before P13-3 still bind master's score headers after landing."""
import pytest

from tests.replay import cmdtext
from tests.replay.pipeline import Orchestrator


@pytest.mark.parametrize("role", ["BA", "DEV", "QA"])
def test_render_binds_the_legacy_score_headers(role):
    orch = Orchestrator.__new__(Orchestrator)
    orch.line_rules, orch.rules = [], []
    orch.values = {f"{role}_SCORE_HEADER": f"record for {role}"}
    prompt = f"You are {role}.\n<{role}_SCORE_HEADER prepended here>\nRead the task."
    assert orch.render({"prompt": prompt}, "20261101-100000") == f"You are {role}.\nrecord for {role}\nRead the task."
    orch.values.clear()
    assert orch.render({"prompt": prompt}, "20261101-100000") == f"You are {role}.\n\nRead the task."
    with pytest.raises(cmdtext.TextNotFound, match="unbound placeholders"):
        orch.render({"prompt": "<UNBOUND>"}, "20261101-100000")
