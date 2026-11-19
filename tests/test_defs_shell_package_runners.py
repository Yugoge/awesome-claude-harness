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

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path[:0] = [str(HOOKS), str(HOOKS / "lib")]  # as a hook runs: runtime_guard importable from hooks/lib

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


@pytest.mark.parametrize("command", ["systemctl restart myd", "service myd restart", "initctl restart myd"])
def test_the_daemon_rule_and_the_runtime_guard_read_one_set_of_service_managers(command):
    """bash_safety_rules.daemon_restart refuses a restart verb on the service manager the runtime
    guard blocks; it read {systemctl, service} while the guard reads {systemctl, service, initctl}
    (family service-managers)."""
    from lib import bash_safety_rules
    assert bash_safety_rules.daemon_restart(command, {"tool_input": {}}, "myd") is True
    assert bash_safety_rules.daemon_restart("initctl status myd", {"tool_input": {}}, "myd") is False
