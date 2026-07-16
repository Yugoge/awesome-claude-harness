#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.anchor.

Imports the anchor sibling module DIRECTLY (not via the _core facade) and
unit-tests its extracted P0-anchor helper predicates in isolation:
_anchor_exec_tokens, _anchor_in_launch_position, _fused_option_values,
_anchor_service_hits_protected, _anchor_nonprotected_workspace_selector.
Crafted argv token lists in, predicate/structure out — NOT full evaluate() e2e.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import anchor  # noqa: E402  DIRECT module import


def test_module_identity():
    assert anchor.__name__ == "lib.runtime_guard.anchor"


# ── _anchor_exec_tokens ──────────────────────────────────────────────────────

def test_anchor_exec_tokens_basic():
    assert anchor._anchor_exec_tokens(["node", "x.js"]) == [(0, "node"), (1, "x.js")]


def test_anchor_exec_tokens_skips_env_prefix_and_options():
    # VAR=val env-prefix and leading-'-' options are excluded; barewords kept.
    assert anchor._anchor_exec_tokens(["FOO=bar", "node", "-e", "code"]) == [(1, "node"), (3, "code")]


def test_anchor_exec_tokens_skips_redirection_target():
    assert anchor._anchor_exec_tokens(["echo", "x", ">", "out"]) == [(0, "echo"), (1, "x")]


def test_anchor_exec_tokens_keeps_dashdash_as_position_anchor():
    assert anchor._anchor_exec_tokens(["env", "--", "node"]) == [(0, "env"), (1, "--"), (2, "node")]


# ── _anchor_in_launch_position ───────────────────────────────────────────────

def test_launch_position_first_token():
    assert anchor._anchor_in_launch_position(["happy", "daemon"], 0) is True


def test_launch_position_after_runtime():
    assert anchor._anchor_in_launch_position(["node", "app.js"], 1) is True


def test_launch_position_after_dashdash():
    assert anchor._anchor_in_launch_position(["--", "happy"], 1) is True


def test_launch_position_followed_by_launch_subcmd():
    assert anchor._anchor_in_launch_position(["wrapper", "happy", "daemon"], 1) is True


def test_launch_position_argument_is_not_a_launch():
    # `cp <path> dst` — <path> at pos 1 is a data operand, not a launch.
    assert anchor._anchor_in_launch_position(["cp", "file", "dst"], 1) is False


# ── _fused_option_values ─────────────────────────────────────────────────────

def test_fused_option_values():
    assert anchor._fused_option_values(["--exec=/a/b", "node"]) == ["/a/b"]
    assert anchor._fused_option_values(["-o=val", "x"]) == ["val"]
    # a non-fused flag / a plain bareword yield nothing.
    assert anchor._fused_option_values(["plain", "--flag"]) == []


# ── _anchor_service_hits_protected ───────────────────────────────────────────

def _exec(toks):
    return anchor._anchor_exec_tokens(toks)


def test_service_hit_direct():
    toks = ["systemctl", "restart", "happy-daemon"]
    assert anchor._anchor_service_hits_protected(toks, _exec(toks), ["happy-daemon"]) is True


def test_service_hit_behind_wrapper():
    toks = ["sudo", "systemctl", "stop", "happy-daemon"]
    assert anchor._anchor_service_hits_protected(toks, _exec(toks), ["happy-daemon"]) is True


def test_service_hit_non_manager_head_is_false():
    # `docker restart happy-daemon` — docker is not a service manager program.
    toks = ["docker", "restart", "happy-daemon"]
    assert anchor._anchor_service_hits_protected(toks, _exec(toks), ["happy-daemon"]) is False


def test_service_hit_unrelated_unit_is_false():
    # verb present, but the protected unit is not in the manager's own argv.
    toks = ["systemctl", "restart", "other-unit"]
    assert anchor._anchor_service_hits_protected(toks, _exec(toks), ["happy-daemon"]) is False


def test_service_hit_template_instance_form():
    toks = ["systemctl", "restart", "happy-daemon@1.service"]
    assert anchor._anchor_service_hits_protected(toks, _exec(toks), ["happy-daemon"]) is True


# ── _anchor_nonprotected_workspace_selector ──────────────────────────────────

_CFG = {"non_protected_workspaces": ["app"], "protected_build_workspaces": ["core"]}


def test_ws_selector_single_nonprotected_exempts():
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "workspace", "app", "build"], _CFG) is True


def test_ws_selector_protected_not_exempt():
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "workspace", "core", "build"], _CFG) is False


def test_ws_selector_recursive_flag_voids_exemption():
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "-r", "workspace", "app", "build"], _CFG) is False


def test_ws_selector_unknown_fails_closed():
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "workspace", "mystery", "build"], _CFG) is False


def test_ws_selector_glob_selector_not_exempt():
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "--filter", "*", "build"], _CFG) is False


def test_ws_selector_multiple_selectors_not_exempt():
    # two selectors could fan into the protected workspace → not exempt.
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "-w", "app", "-w", "app", "build"], _CFG) is False


def test_ws_selector_empty_nonprotected_config_is_false():
    assert anchor._anchor_nonprotected_workspace_selector(
        ["yarn", "workspace", "app", "build"], {"non_protected_workspaces": []}) is False
