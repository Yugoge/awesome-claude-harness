"""tests/replay/launchdiff.py compares each launcher event's hooks with the old path, normalised.

A clock reading a hook prints is not a difference: posttool-overnight-loop.py prints "Time remaining:
7h 59m", and when a minute boundary falls between the launcher's run and the old path's the two
records differ by one minute (seen as replay shard 2/6 failing on #44's CI). So is the minute count of
scripts/create-overnight-state.sh's short-window warning, which prompt-workflow.py passes on at
/dev-overnight: "time budget <1h (10m)" in one path and "(9m)" in the other when a second ticks
between the script's two clock reads (seen as replay shard 6/6 failing on #29's CI, D20's 10-minute
window). The same two reads decide whether the warning is printed at all: with a 60-minute window one
path prints "(59m)" and the other nothing. A real difference in the same text still is one.
"""
from tests.replay import launchdiff

# The /dev-overnight stderr prompt-workflow.py passes on from create-overnight-state.sh (its WARNING line
# word for word), with a 10-minute window typed as "10m"; the minute count is the only part that moves.
_LAUNCH = ("WARNING: time budget <1h ({m}). Recommended minimum: 1h for 1 pipeline; 2h for 2-3 pipelines; "
           "6h+ for overnight.\nIn-place mode: working directly in <project> on branch 'night-work' (no worktree "
           "created). Pass --worktree to isolate.\nCreated overnight state v9: <state>\n  End time: <ts>\n"
           "  Spec mode: {spec}\n  Isolation: in_place\n  Working root: <project>\n  Branch: night-work\n")


class _Rp:
    class layout:
        harness = "/nonexistent"

    @staticmethod
    def norm_text(text):
        return text


def _rec(hook, key, text):
    return dict({"hook": hook, "rc": 0, "stdout": "", "stderr": ""}, **{key: text})


def _diffs(monkeypatch, old_out, new_out, hook="hooks/posttool-overnight-loop.py", key="stdout"):
    monkeypatch.setattr(launchdiff, "_combine", lambda harness, event, old: (0, old[0]["stdout"], old[0]["stderr"]))
    new = _rec(hook, key, new_out)
    launched = {"rules": [new], "rc": 0, "stdout": new["stdout"], "stderr": new["stderr"]}
    return launchdiff.compare(_Rp, "PostToolUse", launched, [_rec(hook, key, old_out)])


def _launch(monkeypatch, old_out, new_out):
    return _diffs(monkeypatch, old_out, new_out, "hooks/prompt-workflow.py", "stderr")


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


def test_the_short_window_warnings_minute_count_is_no_difference(monkeypatch):
    assert _launch(monkeypatch, _LAUNCH.format(m="9m", spec="autonomous"),
                   _LAUNCH.format(m="10m", spec="autonomous")) == []


def test_a_real_difference_beside_the_short_window_warning_is_still_one(monkeypatch):
    diffs = _launch(monkeypatch, _LAUNCH.format(m="9m", spec="autonomous"),
                    _LAUNCH.format(m="10m", spec="user-provided"))
    assert [d["what"] for d in diffs] == ["hooks/prompt-workflow.py stderr", "answer stderr"]
    assert "Spec mode: autonomous" in diffs[0]["old"] and "Spec mode: user-provided" in diffs[0]["new"]


def test_only_the_warnings_minute_count_is_normalised(monkeypatch):
    # the same digits in any other form (the end time as typed, a count of minutes elsewhere) still differ
    assert len(_launch(monkeypatch, "/dev-overnight 9m toy\n", "/dev-overnight 10m toy\n")) == 2
    assert len(_launch(monkeypatch, "time budget <1h (9m)\n", "time budget <1h (9h)\n")) == 2
    assert len(_launch(monkeypatch, "time budget <2h (9m)\n", "time budget <2h (10m)\n")) == 2


def test_the_warning_either_side_of_the_60_minute_mark_is_no_difference(monkeypatch):
    with_line = _LAUNCH.format(m="59m", spec="autonomous")
    without = with_line.split("\n", 1)[1]
    assert without.startswith("In-place mode:")
    assert _launch(monkeypatch, with_line, without) == []
    assert _launch(monkeypatch, without, with_line) == []


def test_a_warning_missing_at_any_other_count_or_beside_a_real_difference_is_still_one(monkeypatch):
    without = _LAUNCH.format(m="9m", spec="autonomous").split("\n", 1)[1]
    for m in ("10m", "58m", "60m"):
        assert len(_launch(monkeypatch, _LAUNCH.format(m=m, spec="autonomous"), without)) == 2, m
    diffs = _launch(monkeypatch, _LAUNCH.format(m="59m", spec="autonomous"),
                    without.replace("Spec mode: autonomous", "Spec mode: user-provided"))
    assert [d["what"] for d in diffs] == ["hooks/prompt-workflow.py stderr", "answer stderr"]
