"""What a replay's record keeps of the sandbox's out/ directory, and what a failed run says about itself.

scorelog.resweep leaves a symlink in out/ (score-rebuild/home/.claude/hooks) whose target is a path of the sandbox's own
namespace. The command that collects out/ runs outside that namespace, where the path is the host's (the installed harness, on a
machine that has one: the copy then followed the link and passed) or nothing (CI: the copy raised on the dangling link after the
replay had passed, and every score-log replay ended with exit 1). The record keeps the link as a link; and a run that ends
non-zero says why in the failure message of the assertion that reads it.
"""
from __future__ import annotations

import os

from tests.replay import cli, suite


def test_a_link_to_a_path_that_exists_only_in_the_sandbox_is_kept_as_a_link(tmp_path):
    sb, record = tmp_path / "sb", tmp_path / "record"
    inside = sb / "out" / "score-rebuild" / "home" / ".claude"
    inside.mkdir(parents=True)
    (sb / "out" / "summary.json").write_text("{}")
    target = str(tmp_path / "namespace-only" / "hooks")  # not there, as the sandbox's own home is not outside it
    os.symlink(target, inside / "hooks")
    cli.copy_out(str(sb), str(record))
    kept = record / "score-rebuild" / "home" / ".claude" / "hooks"
    assert os.path.islink(kept) and os.readlink(kept) == target and (record / "summary.json").is_file()


def test_a_non_zero_exit_carries_the_replay_commands_own_output(tmp_path):
    (tmp_path / "replay.log").write_text("Traceback (most recent call last):\n  ...\nshutil.Error: [('a', 'b', 'No such file')]\n")
    scn = suite.Scenario("score: unit", "dev", (), ("dev",), 1)
    said = suite.Result(scn, "shipped", str(tmp_path), 1, 0.0).explain()
    assert "shutil.Error" in said and "rc 1" in said
    assert "replay.log" not in suite.Result(scn, "shipped", str(tmp_path), 0, 0.0).explain()
