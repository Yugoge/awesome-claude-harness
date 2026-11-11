"""tests/replay/launchdiff.py compares each launcher event's hooks with the old path, normalised.

A clock reading a hook prints is not a difference: posttool-overnight-loop.py prints "Time remaining:
7h 59m", and when a minute boundary falls between the launcher's run and the old path's the two
records differ by one minute (seen as replay shard 2/6 failing on #44's CI). A real difference in
the same text still is one.
"""
from tests.replay import launchdiff


class _Rp:
    class layout:
        harness = "/nonexistent"

    @staticmethod
    def norm_text(text):
        return text


def _rec(stdout):
    return {"hook": "hooks/posttool-overnight-loop.py", "rc": 0, "stdout": stdout, "stderr": ""}


def _diffs(monkeypatch, old_out, new_out):
    monkeypatch.setattr(launchdiff, "_combine", lambda harness, event, old: (0, old[0]["stdout"], ""))
    launched = {"rules": [_rec(new_out)], "rc": 0, "stdout": new_out, "stderr": ""}
    return launchdiff.compare(_Rp, "PostToolUse", launched, [_rec(old_out)])


def test_a_clock_reading_one_minute_apart_is_no_difference(monkeypatch):
    assert _diffs(monkeypatch, "Time remaining: 7h 59m\nIssues fixed this session: 2\n",
                  "Time remaining: 7h 58m\nIssues fixed this session: 2\n") == []


def test_a_real_difference_beside_the_clock_reading_is_still_one(monkeypatch):
    diffs = _diffs(monkeypatch, "Time remaining: 7h 59m\nIssues fixed this session: 2\n",
                   "Time remaining: 7h 58m\nIssues fixed this session: 3\n")
    assert [d["what"] for d in diffs] == ["hooks/posttool-overnight-loop.py stdout", "answer stdout"]
