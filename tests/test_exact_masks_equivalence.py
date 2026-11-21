"""stage-owned-hunks._exact_masks builds its LCS tables by bit-parallel rows (_lcs_rows) for speed:
the tables and the three mask sets must be exactly those of the cell-by-cell definition."""
import importlib.util
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("soh_masks", ROOT / "scripts" / "stage-owned-hunks.py")
soh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soh)


def _reference(pm, qm):
    a, b = len(pm), len(qm)
    if a == 0 or b == 0:
        return frozenset(range(a)), frozenset(range(b)), {}
    pre = [[0] * (b + 1) for _ in range(a + 1)]
    for i in range(a):
        for j in range(b):
            pre[i + 1][j + 1] = pre[i][j] + 1 if pm[i] == qm[j] else max(pre[i + 1][j], pre[i][j + 1])
    suf = [[0] * (b + 1) for _ in range(a + 1)]
    for i in range(a - 1, -1, -1):
        for j in range(b - 1, -1, -1):
            suf[i][j] = suf[i + 1][j + 1] + 1 if pm[i] == qm[j] else max(suf[i + 1][j], suf[i][j + 1])
    total = pre[a][b]
    p_changed = {i for i in range(a) if any(pre[i][j] + suf[i + 1][j] == total for j in range(b + 1))}
    q_changed = {j for j in range(b) if any(pre[i][j] + suf[i][j + 1] == total for i in range(a + 1))}
    images = {}
    for i in range(a):
        t = frozenset(j for j in range(b) if pm[i] == qm[j] and pre[i][j] + 1 + suf[i + 1][j + 1] == total)
        if t:
            images[i] = t
    return frozenset(p_changed), frozenset(q_changed), images


def test_bit_parallel_masks_equal_the_cell_by_cell_definition():
    r = random.Random(20261120)
    for _ in range(1500):
        alphabet = r.choice([b"ab", b"abc", b"a\n ", bytes(range(256))])
        p = bytes(r.choice(alphabet) for _ in range(r.randint(0, 16)))
        q = bytes(r.choice(alphabet) for _ in range(r.randint(0, 16)))
        assert soh._exact_masks(p, q) == _reference(p, q), (p, q)
    assert soh._lcs_rows(b"abcb", b"bcab")[-1] == [0, 1, 2, 2, 3]
