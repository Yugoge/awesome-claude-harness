#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.constants.

Imports the constants sibling module DIRECTLY (not via the _core facade) and
asserts the pure data tables exist, carry the expected container types
(frozenset / dict), and contain a few KNOWN members — a guard against accidental
edits to the vocabularies that drive the whole engine. NOT an evaluate() e2e test.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import constants  # noqa: E402  DIRECT module import


def test_module_identity():
    assert constants.__name__ == "lib.runtime_guard.constants"


# ── frozenset vocabularies: type + known members ─────────────────────────────

def test_pkg_managers():
    assert isinstance(constants.PKG_MANAGERS, frozenset)
    assert {"yarn", "npm", "pnpm", "bun"} <= constants.PKG_MANAGERS


def test_runtimes():
    assert isinstance(constants.RUNTIMES, frozenset)
    assert {"node", "tsx", "bun", "deno"} <= constants.RUNTIMES


def test_kill_verbs_include_kills_exclude_readonly():
    assert isinstance(constants.KILL_VERBS, frozenset)
    assert {"kill", "pkill", "killall"} <= constants.KILL_VERBS
    # lsof / fuser are read-only inspectors — they must NOT be kill verbs.
    assert "lsof" not in constants.KILL_VERBS
    assert "fuser" not in constants.KILL_VERBS


def test_service_verbs():
    assert isinstance(constants.SERVICE_VERBS, frozenset)
    assert {"start", "stop", "restart", "disable", "enable", "mask"} <= constants.SERVICE_VERBS


def test_mutation_verbs():
    assert isinstance(constants.MUTATION_VERBS, frozenset)
    assert {"cp", "mv", "touch", "truncate", "dd"} <= constants.MUTATION_VERBS


def test_env_wrappers():
    assert isinstance(constants.ENV_WRAPPERS, frozenset)
    assert {"env", "sudo", "nohup", "timeout", "exec"} <= constants.ENV_WRAPPERS


def test_read_inspect_edit_allowlist():
    assert isinstance(constants.READ_INSPECT_EDIT_ALLOWLIST, frozenset)
    # a few stable read/inspect/search heads
    assert {"cat", "grep", "ls", "find", "echo"} <= constants.READ_INSPECT_EDIT_ALLOWLIST


def test_exec_runner_tokens():
    assert isinstance(constants.EXEC_RUNNER_TOKENS, frozenset)
    assert {"npx", "node", "bunx", "dlx"} <= constants.EXEC_RUNNER_TOKENS


def test_dep_builtins():
    assert isinstance(constants.DEP_BUILTINS, frozenset)
    assert {"install", "add", "remove"} <= constants.DEP_BUILTINS


def test_build_tool_basenames():
    assert isinstance(constants.BUILD_TOOL_BASENAMES, frozenset)
    assert {"tsc", "vite", "webpack"} <= constants.BUILD_TOOL_BASENAMES


def test_git_readonly_subcmds():
    assert isinstance(constants._GIT_READONLY_SUBCMDS, frozenset)
    assert {"status", "log", "diff", "show"} <= constants._GIT_READONLY_SUBCMDS


# ── dict tables: type + shape ────────────────────────────────────────────────

def test_wrapper_opts_with_arg_is_dict():
    assert isinstance(constants._WRAPPER_OPTS_WITH_ARG, dict)
    # timeout consumes `-s`/`--signal`/`-k`/`--kill-after` as value options.
    assert "timeout" in constants._WRAPPER_OPTS_WITH_ARG
    assert isinstance(constants._WRAPPER_OPTS_WITH_ARG["timeout"], frozenset)
    assert "--signal" in constants._WRAPPER_OPTS_WITH_ARG["timeout"]


def test_exec_frontend_profiles_shape():
    assert isinstance(constants.EXEC_FRONTEND_PROFILES, dict)
    # flock takes exactly one leading positional (the lockfile) before the tail.
    assert constants.EXEC_FRONTEND_PROFILES["flock"]["leading_positionals"] == 1
    # watch joins its whole trailing argv into a shell-evaluated string.
    assert constants.EXEC_FRONTEND_PROFILES["watch"].get("joins_tail_as_shell") is True
    # every profile carries an opts_with_arg frozenset.
    for name, prof in constants.EXEC_FRONTEND_PROFILES.items():
        assert isinstance(prof, dict), name
        assert isinstance(prof["opts_with_arg"], frozenset), name


def test_wrapper_leading_positional_membership():
    assert isinstance(constants._WRAPPER_LEADING_POSITIONAL, frozenset)
    assert {"timeout", "setarch"} <= constants._WRAPPER_LEADING_POSITIONAL
