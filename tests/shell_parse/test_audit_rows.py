"""Every input of the P14 parser audit: the parser reaches each program bash runs, or says it cannot.

audit_rows.json holds the 131 inputs of the independent audit with, for each,
what bash 5.2 did with it in a sandbox (bwrap, no network): the programs it ran
(``bash_runs``, by xtrace and a logging stub for every program name the input
mentions), the argv of every git it ran (``git_calls``, by the stub) and every
file the run created (``writes``). For each input:

  * every program is a command ``walk`` reaches;
  * every git call is a ``git_invocations`` entry with the same subcommand;
  * every written file is a ``write_targets`` path, or an undecidable target
    stands for it;

or else the parse carries a marker a consumer fails closed on: a ParseError, a
computed command word, a templated payload or an unresolved reading.
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


def _git_subcommand(argv):
    k = 1
    while k < len(argv):
        a = argv[k]
        if a in sp.GIT_GLOBAL_VALUE_OPTS:
            k += 2
        elif (a.startswith("--") and "=" in a) or a in sp.GIT_GLOBAL_FLAGS:
            k += 1
        else:
            break
    return argv[k] if k < len(argv) else None


@pytest.mark.parametrize("row", [r for r in ROWS if r["git_calls"]],
                         ids=lambda r: r["input"][:40])
def test_every_git_call_is_an_invocation_or_marked(row):
    invs = sp.git_invocations(row["input"], strings=True)
    subs = {g.subcommand for g in invs}
    _names, markers = reading(row["input"])
    for call in row["git_calls"]:
        assert _git_subcommand(call) in subs or markers or any(g.unresolved for g in invs), (
            row["input"], call)


@pytest.mark.parametrize("row", [r for r in ROWS if r["writes"]], ids=lambda r: r["input"][:40])
def test_every_written_file_is_a_target_or_undecidable(row):
    targets = sp.write_targets(row["input"])
    paths = {os.path.normpath(t.path) for t in targets if t.path}
    _names, markers = reading(row["input"])
    for f in row["writes"]:
        assert f in paths or any(not t.decidable for t in targets) or markers, (row["input"], f)
