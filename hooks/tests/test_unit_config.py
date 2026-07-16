#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.config.

Imports the config sibling module DIRECTLY (not via the _core facade) and
unit-tests its config-loading + STEP0 self-protection helpers in isolation:
DATA_FILE_PATH import-time env-read semantics, _load_config (schema-validated
fail-closed load), _config_path_variants, _targets_config_file.

DATA_FILE_PATH is read at MODULE-IMPORT time from the env var, so the fixture
sets CLAUDE_PROTECTED_RUNTIME_FILE to a throwaway temp path, importlib.reload()s
the module, and asserts the path tracks. The live machine file is NEVER touched.
The fixture restores the env var and reloads at teardown so no other test file is
perturbed.
"""

from __future__ import annotations

import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import config as _config_import  # noqa: E402  DIRECT import

_ENV = "CLAUDE_PROTECTED_RUNTIME_FILE"

_VALID_CFG = {
    "schema_version": 1,
    "protected_cmds": ["demo"],
    "protected_launch_paths": [],
    "protected_services": [],
    "protected_hotfiles": [],
    "protected_statefiles": [],
    "protected_endpoint_paths": [],
    "protected_proc_idents": [],
    "protected_global_bins": [],
    "protected_build_workspaces": [],
    "protected_build_paths": [],
}


@pytest.fixture
def cfg_at(tmp_path):
    """Reload config with DATA_FILE_PATH pointed at a caller-written temp file.

    Yields a helper: cfg_at(contents) writes `contents` (str|dict|None) to the
    temp path (None = leave file absent), sets the env var, reloads the module,
    and returns (module, path). Restores env + reloads at teardown.
    """
    saved = os.environ.get(_ENV)
    path = tmp_path / "protected-runtime.json"

    def _apply(contents="__valid__"):
        if contents is None:
            if path.exists():
                path.unlink()
        else:
            if contents == "__valid__":
                path.write_text(json.dumps(_VALID_CFG))
            elif isinstance(contents, (dict, list)):
                path.write_text(json.dumps(contents))
            else:
                path.write_text(contents)
        os.environ[_ENV] = str(path)
        importlib.reload(_config_import)
        return _config_import, str(path)

    yield _apply

    if saved is None:
        os.environ.pop(_ENV, None)
    else:
        os.environ[_ENV] = saved
    importlib.reload(_config_import)


def test_module_identity():
    assert _config_import.__name__ == "lib.runtime_guard.config"


# ── DATA_FILE_PATH import-time env-read semantics ────────────────────────────

def test_data_file_path_tracks_env_on_reload(cfg_at):
    mod, path = cfg_at("__valid__")
    assert mod.DATA_FILE_PATH == path


# ── _load_config (schema-validated, fail-closed) ─────────────────────────────

def test_load_config_valid(cfg_at):
    mod, _ = cfg_at("__valid__")
    cfg = mod._load_config()
    assert isinstance(cfg, dict)
    assert cfg["schema_version"] == 1
    assert cfg["protected_cmds"] == ["demo"]


def test_load_config_missing_file_is_none(cfg_at):
    mod, _ = cfg_at(None)  # no file present
    assert mod._load_config() is None


def test_load_config_bad_schema_version_is_none(cfg_at):
    bad = dict(_VALID_CFG)
    bad["schema_version"] = 2
    mod, _ = cfg_at(bad)
    assert mod._load_config() is None


def test_load_config_missing_required_key_is_none(cfg_at):
    bad = dict(_VALID_CFG)
    del bad["protected_cmds"]
    mod, _ = cfg_at(bad)
    assert mod._load_config() is None


def test_load_config_required_key_wrong_type_is_none(cfg_at):
    bad = dict(_VALID_CFG)
    bad["protected_cmds"] = "not-a-list"
    mod, _ = cfg_at(bad)
    assert mod._load_config() is None


def test_load_config_non_dict_json_is_none(cfg_at):
    mod, _ = cfg_at("[1, 2, 3]")  # valid JSON, but a list not a dict
    assert mod._load_config() is None


def test_load_config_malformed_json_is_none(cfg_at):
    mod, _ = cfg_at("{ not valid json ")
    assert mod._load_config() is None


# ── _config_path_variants ────────────────────────────────────────────────────

def test_config_path_variants_include_data_file_path(cfg_at):
    mod, path = cfg_at("__valid__")
    variants = mod._config_path_variants()
    assert isinstance(variants, set)
    assert path in variants
    assert os.path.normpath(path) in variants


# ── _targets_config_file ─────────────────────────────────────────────────────

def test_targets_config_file_redirect(cfg_at):
    mod, path = cfg_at("__valid__")
    cmd = f"echo {{}} > {path}"
    assert mod._targets_config_file(cmd, ["echo", "{}", ">", path]) is True


def test_targets_config_file_bareword_token(cfg_at):
    mod, path = cfg_at("__valid__")
    # `rm <config>` names the config path as a bareword operand.
    assert mod._targets_config_file(f"rm {path}", ["rm", path]) is True


def test_targets_config_file_unrelated_is_false(cfg_at):
    mod, _ = cfg_at("__valid__")
    assert mod._targets_config_file("echo hello > /tmp/other", ["echo", "hello", ">", "/tmp/other"]) is False
