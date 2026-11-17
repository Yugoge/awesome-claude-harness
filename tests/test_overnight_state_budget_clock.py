"""scripts/create-overnight-state.sh derives every time of a launch from one reading of the clock.

The launch's start time, its end time (relative: Nm, Nh, the default 8h; or a clock time, rolled
over to tomorrow once it has passed today) and the "time budget <1h" warning are all differences
from "now". When each read the clock afresh, a second boundary falling between two readings moved
one against the other: an end time of `9m` warned of a budget of 9m or of 8m depending on where
the boundary fell, and replay shard 6/6 failed its launch differential on
test_f6o_usage_limit_before_end_time_resumed_by_the_wake[armed], the launcher's run of the script
reading 9m and the old path's reading 8m.

Here the boundary always falls: a fake `date` on PATH advances its clock one second on every
reading of now (a `date` with no -d, or with a -d relative to now). A script that reads the clock
once sees no boundary at all, so its budget reads exactly the minutes it was given and its record's
end_time lies exactly that far from its start_time. On a21dcbf9, which read the clock up to four
times per launch, the budget reads one minute short and the record's span one second long.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "create-overnight-state.sh"
SID = "5b1c0d2e-3f4a-4b5c-8d6e-7f8091a2b3c4"
WARNING = re.compile(r"WARNING: time budget <1h \((\d+)m\)")

# A `date` whose clock advances one second on every reading of now. A -d naming an absolute
# time (@epoch, or one starting with a YYYY-MM-DD date) reads no clock and passes through; a -d
# relative to now is resolved against the fake clock; any other -d fails loudly, so a reading of
# the real clock can never slip past the fake one.
FAKE_DATE = r"""#!/bin/bash
set -euo pipefail
real="$FAKE_DATE_REAL"
tick() {
    local n
    n=$(( $(cat "$FAKE_DATE_TICKS") + 1 ))
    echo "$n" > "$FAKE_DATE_TICKS"
    now=$(( FAKE_DATE_START + n - 1 ))
}
args=()
spec=""
has_d=0
while (( $# )); do
    case "$1" in
        -d) spec="$2"; has_d=1; shift 2 ;;
        --date=*) spec="${1#--date=}"; has_d=1; shift ;;
        *) args+=("$1"); shift ;;
    esac
done
if (( ! has_d )); then
    tick
    exec "$real" -d "@$now" "${args[@]}"
fi
case "$spec" in
    @*|[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*) exec "$real" -d "$spec" "${args[@]}" ;;
esac
if [[ "$spec" =~ ^\+([0-9]+)\ (minutes|hours)$ ]]; then
    tick
    unit=60
    [[ "${BASH_REMATCH[2]}" == hours ]] && unit=3600
    exec "$real" -d "@$(( now + BASH_REMATCH[1] * unit ))" "${args[@]}"
fi
if [[ "$spec" =~ ^(today|tomorrow)\ .+$ ]]; then
    tick
    exec "$real" -d "$("$real" -d "@$now" +%Y-%m-%d) $spec" "${args[@]}"
fi
echo "fake date: no rule for -d '$spec'" >&2
exit 97
"""


def _epoch(iso: str) -> int:
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def launch(tmp_path):
    """Run the launcher's record-only mode (it writes nothing) in a scratch repository, its first
    reading of now at `start`; return (record, warned budgets in minutes)."""
    real = shutil.which("date")
    assert real, "no date on PATH"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "date"
    fake.write_text(FAKE_DATE, encoding="utf-8")
    fake.chmod(0o755)
    ticks = tmp_path / "ticks"
    repo = tmp_path / "repo"
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": str(tmp_path),
           "TZ": "UTC", "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
           "FAKE_DATE_REAL": real, "FAKE_DATE_TICKS": str(ticks)}
    for name in ("CLAUDE_OVERNIGHT_ACTOR", "CLAUDE_PROJECT_DIR", "CLAUDE_SESSION_ID"):
        env.pop(name, None)

    def git(*args):
        done = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr

    repo.mkdir()
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "init")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git("checkout", "-q", "-b", "work")

    def run(start: str, end_time: str | None):
        ticks.write_text("0")
        run_env = dict(env, FAKE_DATE_START=str(_epoch(start)))
        # The premise: two readings of now through the fake are a second apart.
        two = [subprocess.run(["date", "-u", "+%s"], env=run_env, capture_output=True, text=True,
                              check=True).stdout.strip() for _ in range(2)]
        assert int(two[1]) - int(two[0]) == 1 and int(two[0]) == _epoch(start), two
        ticks.write_text("0")
        argv = ["bash", str(SCRIPT), "--emit-record-only", "--session-id", SID, "--project-dir", str(repo)]
        if end_time is not None:
            argv += ["--end-time", end_time]
        done = subprocess.run(argv, cwd=repo, env=run_env, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout), [int(m) for m in WARNING.findall(done.stderr)]

    return run


@pytest.mark.parametrize("end_time, minutes, warned", [
    pytest.param("9m", 9, [9], id="9m"),
    pytest.param("+9m", 9, [9], id="+9m"),
    pytest.param("0.5h", 30, [30], id="0.5h"),
    pytest.param("1h", 60, [], id="1h"),
    pytest.param(None, 8 * 60, [], id="default-8h"),
])
def test_a_relative_end_time_and_its_budget_share_one_clock_reading(launch, end_time, minutes, warned):
    record, budget = launch("2030-01-01T12:00:00Z", end_time)
    assert budget == warned
    assert record["start_time"] == "2030-01-01T12:00:00Z"
    assert _epoch(record["end_time"]) - _epoch(record["start_time"]) == minutes * 60


@pytest.mark.parametrize("start, end_time, end, warned", [
    pytest.param("2030-01-01T12:00:00Z", "12:30", "2030-01-01T12:30:00Z", [30], id="later-today"),
    pytest.param("2030-01-01T12:00:00Z", "11:30", "2030-01-02T11:30:00Z", [], id="passed-rolls-to-tomorrow"),
    pytest.param("2030-01-01T23:59:59Z", "00:30", "2030-01-02T00:30:00Z", [30], id="across-midnight"),
])
def test_a_clock_time_end_and_its_budget_share_one_clock_reading(launch, start, end_time, end, warned):
    record, budget = launch(start, end_time)
    assert budget == warned
    assert record["start_time"] == start
    assert record["end_time"] == end
