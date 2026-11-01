"""The replay suite's session runner and its CI split (tests/replay/suite.py).

Every test that replays asks for the `replays` fixture with a marker naming what it needs:
`@pytest.mark.replay(key)` where key is the replay's (scenario key + tag, settings) as
`suite.replay_key` builds it. Before the first such test runs, the session replays every key its
selected tests name, REPLAY_WORKERS at a time, so the replays of one job run side by side.

REPLAY_SHARD=i/n (CI) keeps the tests of the replays shard i of n owns: each replay goes, costliest
first, to the shard with the least cost so far (each replay whole in one shard), and the tests that
replay nothing (unit tests) to shard 1; a test marked `every_shard` (it reads the replays its shard
ran) to every shard. A test may carry several `replay` markers (it reads every one of those
replays): the replays one test names, and those any other test names with one of them, go to one
shard together. REPLAY_WORK keeps the runs (default: pytest's temp dir).
"""
from __future__ import annotations

import os

import pytest

from tests.replay import suite


def pytest_configure(config):
    config.addinivalue_line("markers", "replay(key, cost): the test reads replay `key` (suite.replay_key)")
    config.addinivalue_line("markers", "every_shard: the test reads whatever replays its shard ran; it runs in every shard")


def _keys(item) -> list:
    """(key, cost) of every replay the test reads (its `replay` markers)."""
    return [(m.args[0], m.args[1] if len(m.args) > 1 else 100) for m in item.iter_markers("replay")]


def pytest_collection_modifyitems(config, items):
    shard = os.environ.get("REPLAY_SHARD", "")
    if not shard:
        return
    i, _, n = shard.partition("/")
    i, n = int(i), int(n)
    costs: dict = {}
    group: dict = {}  # replay key -> the key standing for every replay read together with it

    def root(k):
        while group.setdefault(k, k) != k:
            k = group[k]
        return k
    for it in items:
        ks = _keys(it)
        for k, c in ks:
            costs[k] = max(costs.get(k, 0), c)
            group[root(k)] = root(ks[0][0])
    groups: dict = {}
    for k, c in costs.items():
        groups.setdefault(root(k), []).append(k)
    load = [0.0] * n
    owner = {}
    for keys in sorted(groups.values(), key=lambda ks: (-sum(costs[k] for k in ks), str(sorted(ks)))):
        j = min(range(n), key=lambda x: (load[x], x))
        for k in keys:
            owner[k] = j + 1
        load[j] += sum(costs[k] for k in keys)
    keep, drop = [], []
    for it in items:
        ks = _keys(it)
        mine = it.get_closest_marker("every_shard") or (owner.get(ks[0][0]) if ks else 1) == i
        (keep if mine else drop).append(it)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


@pytest.fixture(scope="session")
def runner(tmp_path_factory, request):
    missing = suite.preconditions()
    if missing:
        pytest.fail("the replay suite cannot run here: " + "; ".join(missing), pytrace=False)
    work = os.environ.get("REPLAY_WORK") or str(tmp_path_factory.mktemp("replay"))
    r = suite.Runner(work, log=lambda *a: print(*a, flush=True))
    keys = []
    for it in request.session.items:
        for k, _cost in _keys(it):
            if k not in keys and k in suite.REGISTRY:  # a test with its own runner: not prefetched
                keys.append(k)
    r.prefetch_keys = keys
    yield r
    r.guard.close()


@pytest.fixture
def replays(runner):
    """The session runner, every replay its selected tests name already run."""
    if getattr(runner, "prefetch_keys", None):
        keys, runner.prefetch_keys = runner.prefetch_keys, None
        runner.run_keys(keys)
    return runner
