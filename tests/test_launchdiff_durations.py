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


def test_a_difference_far_from_the_end_of_a_long_text_is_in_view(monkeypatch):
    """compare() kept each side's last 600 characters, so a difference further back was cut off and
    old and new read identical: replay shard 6/6's failure quoted a 979-character stderr whose only
    difference, "time budget <1h (9m)" against "(8m)", was its head. Each side is now quoted as the
    region around the first difference, inside the 300 characters Replay.finish quotes of it."""
    body = "".join(f"line {i}: the same on both sides\n" for i in range(40))
    assert len(body) > 600
    for head, rest in (("", body), (body, "")):
        old = head + "WARNING: time budget <1h (9m). Recommended minimum: 1h\n" + rest
        new = head + "WARNING: time budget <1h (8m). Recommended minimum: 1h\n" + rest
        diffs = _diffs(monkeypatch, old, new)
        assert [d["what"] for d in diffs] == ["hooks/posttool-overnight-loop.py stdout", "answer stdout"]
        for d in diffs:
            assert "<1h (9m)" in d["old"][-300:] and "<1h (8m)" in d["new"][-300:], d
