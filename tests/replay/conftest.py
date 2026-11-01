"""The replay suite's session runner and its CI split (tests/replay/suite.py).

Every test that replays asks for the `replays` fixture with a marker naming what it needs:
`@pytest.mark.replay(key)` where key is the replay's (scenario key + tag, settings) as
`suite.replay_key` builds it. Before the first such test runs, the session replays every key its
selected tests name, REPLAY_WORKERS at a time, so the replays of one job run side by side.

REPLAY_SHARD=i/n (CI) keeps the tests of the replays shard i of n owns: each replay goes, costliest
first, to the shard with the least cost so far (each replay whole in one shard), and the tests that
replay nothing (unit tests) to shard 1; a test marked `every_shard` (it reads the replays its shard
ran) to every shard. REPLAY_WORK keeps the runs (default: pytest's temp dir).
"""
from __future__ import annotations

import os

import pytest

from tests.replay import suite


def pytest_configure(config):
    config.addinivalue_line("markers", "replay(key, cost): the test reads replay `key` (suite.replay_key)")
    config.addinivalue_line("markers", "every_shard: the test reads whatever replays its shard ran; it runs in every shard")


def _key(item):
    m = item.get_closest_marker("replay")
    return (m.args[0], m.args[1] if len(m.args) > 1 else 100) if m else None


def pytest_collection_modifyitems(config, items):
    shard = os.environ.get("REPLAY_SHARD", "")
    if not shard:
        return
    i, _, n = shard.partition("/")
    i, n = int(i), int(n)
    costs: dict = {}
    for it in items:
        k = _key(it)
        if k:
            costs[k[0]] = max(costs.get(k[0], 0), k[1])
    load = [0.0] * n
    owner = {}
    for key, cost in sorted(costs.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        j = min(range(n), key=lambda x: (load[x], x))
        owner[key] = j + 1
        load[j] += cost
    keep, drop = [], []
    for it in items:
        k = _key(it)
        mine = it.get_closest_marker("every_shard") or (owner.get(k[0]) if k else 1) == i
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
        k = _key(it)
        if k and k[0] not in keys:
            keys.append(k[0])
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
