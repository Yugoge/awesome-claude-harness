"""E1: the shared parser reads at least what every existing Bash reader reads.

The corpus is tests/shell_parse/corpus.jsonl: the command strings of the test
files and fixtures (extracted by parsing them, never importing them) and the
generated sweeps of hooks/tests/pol_sweep_generators.py (a seeded sample of the
option-position sweep). differential.py runs the old readers and the new views
on each string; every difference must carry a label. The corpus is split into
shards so pytest-xdist spreads them.
"""

import collections
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import differential as E1  # noqa: E402

SHARDS = 16
with open(os.path.join(HERE, "corpus.jsonl"), encoding="utf-8") as fh:
    CORPUS = [json.loads(line) for line in fh if line.strip()]


def test_corpus_is_the_committed_size():
    assert len(CORPUS) == len(set(CORPUS)) == 30164


@pytest.mark.parametrize("shard", range(SHARDS))
def test_no_unexplained_difference(shard, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    found = []
    labels = collections.Counter()
    for c in CORPUS[shard::SHARDS]:
        m, n = E1.old_facts(c), E1.new_facts(c)
        for reader, label, detail in E1.differences(c, m, n):
            labels[(reader, label)] += 1
            if label is None:
                found.append((reader, c[:120], detail))
    assert found == [], "unexplained differences:\n" + "\n".join(map(repr, found[:40]))


@pytest.mark.parametrize("command,reader,label", [
    ("echo hi # don't", "census", None),
    ("git commit -m a\\; rm x", "allow_subs", "old splits at an escaped separator, `>|` or `|&`"),
    ("tail rm.log", "wt_touched", None),
    ("/bin/rm 2>/dev/null qa-target-1.txt", "wt_touched", None),
])
def test_labels_are_reached(command, reader, label, tmp_path, monkeypatch):
    """The labeller is live: these differences exist and get the label shown (None: no difference)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    diffs = [d for d in E1.differences(command, E1.old_facts(command), E1.new_facts(command))
             if d[0] == reader]
    if label is None:
        assert diffs == []
    else:
        assert diffs and all(d[1] == label for d in diffs), diffs


@pytest.mark.parametrize("command,items,label", [
    ("tail rm.log", ["rm.log"], "O6:old reads an argument word as the write verb"),
    ("/bin/rm 2>/dev/null qa-target-1.txt", ["2"], "O6:old reads a redirection's fd as an operand"),
])
def test_write_target_labels_name_what_the_retired_reader_misread(command, items, label, tmp_path, monkeypatch):
    """lib/bash_write_targets.py is the parser's shim, so the paths its regex reader misread here are
    given to the labeller directly."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert E1._label_items("wt_touched", command, E1.new_facts(command), items) == label


def test_an_unlabelled_difference_fails(monkeypatch):
    """A fact the new view drops is reported unexplained, so the test above can fail."""
    real = E1.new_facts

    def drop_targets(c):
        n = real(c)
        n["resolved_targets"] = []
        n["targets"] = []
        return n

    monkeypatch.setattr(E1, "new_facts", drop_targets)
    assert [d[0] for d in E1.unexplained("echo x > /tmp/e1-probe")] == ["wt_paths", "wt_modes", "wt_touched"]
