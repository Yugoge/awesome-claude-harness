"""Every input of the P14 parser audit: the parser reaches each program bash runs, or says it cannot.

audit_rows.json holds the 131 inputs of the independent audit with, for each, the
programs bash 5.2 ran for it (``bash_runs``), recorded in a sandbox with xtrace
and a logging stub for every program name the input mentions. For each input,
every such program is a command ``walk`` reaches, or the parse carries a marker a
consumer fails closed on: a ParseError, a computed command word, a templated
payload or an unresolved reading.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "hooks", "lib"))
import shell_parse as sp  # noqa: E402

with open(os.path.join(HERE, "audit_rows.json"), encoding="utf-8") as fh:
    ROWS = json.load(fh)


def reading(text):
    script = sp.parse(text)
    names, markers = set(), []
    if script.errors():
        markers.append("error")
    for site in sp.walk(script):
        res = sp.resolve(site.cmd)
        if res.name:
            names.add(res.name)
        if site.cmd.words:
            names.add(os.path.basename(site.cmd.words[0].value() or site.cmd.words[0].text))
        names.update(w[0] for w in res.wrappers)
        if site.dynamic or site.templated:
            markers.append("dynamic")
        if res.unresolved:
            markers.append(res.unresolved)
    return names, markers


def test_the_rows_are_the_audit():
    assert len(ROWS) == 131


@pytest.mark.parametrize("row", ROWS, ids=[str(k) for k in range(len(ROWS))])
def test_every_program_bash_runs_is_reached_or_marked(row):
    names, markers = reading(row["input"])
    missing = sorted(set(row["bash_runs"]) - names)
    assert not missing or markers, (row["input"], missing, row["class"])
