"""The runtime guard reads one set of package-runner programs and one set of package-manager
subcommands that run a package binary (or a script) at every decision.

pnpx (pnpm's runner, `pnpm dlx` under another name) runs a package binary exactly as npx
and bunx do; the 2026-11 duplicate-definition audit found it in one of the guard's seven
runner tables (family pm-exec-runners).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from lib.runtime_guard import _core  # noqa: E402


@pytest.mark.parametrize("runner", ["npx", "pnpx", "bunx"])
def test_every_runner_names_its_target(runner):
    assert _core._package_runner_invocation(runner, ["tsx", "a.ts"]) == ("tsx", ["a.ts"])
    assert _core._tokens_after_runner_target(runner, ["tsc", "-p", "x"]) == ["-p", "x"]


@pytest.mark.parametrize("pm,sub", [("npm", "exec"), ("pnpm", "dlx"), ("yarn", "dlx"), ("bun", "x")])
def test_every_exec_subcommand_names_its_target(pm, sub):
    assert _core._package_runner_invocation(pm, [sub, "tsx", "a.ts"]) == ("tsx", ["a.ts"])


def test_a_run_subcommand_is_no_runner_form():
    assert _core._package_runner_invocation("npm", ["run-script", "build"]) == (None, [])
