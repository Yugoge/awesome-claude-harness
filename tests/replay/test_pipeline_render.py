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


def test_render_binds_the_long_legacy_score_header():
    """The landed /redev text the live-landing variants play carries the header's long form, with
    its placement note after "prepended here"; it binds as the short form does."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.line_rules, orch.rules = [], []
    orch.values = {"BA_SCORE_HEADER": "record for BA"}
    prompt = ("You are BA.\n<BA_SCORE_HEADER prepended here — score-inject output is placed AFTER the role "
              "declaration above and BEFORE the task instructions below, per spec 5.1 line 113: Injection "
              "position: after role declaration, before task instructions>\nRead the task.")
    assert orch.render({"prompt": prompt}, "20261101-100000") == "You are BA.\nrecord for BA\nRead the task."
