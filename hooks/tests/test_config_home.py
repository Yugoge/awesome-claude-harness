"""claude_home.config_home() and its shell twin claude_config_home give one answer for each layout.

The configuration directory as written, unless its settings.json is a link: then the directory the link
resolves into. Both twins compute it from real paths alone (no test of the file), and must agree.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS))

from lib import claude_home  # noqa: E402


def _layouts(tmp: Path) -> dict:
    home = tmp / "harness"
    home.mkdir()
    (home / "settings.json").write_text("{}")
    linked = tmp / "linked"
    linked.mkdir()
    (linked / "settings.json").symlink_to(home / "settings.json")
    plain = tmp / "plain"
    plain.mkdir()
    (plain / "settings.json").write_text("{}")
    via = tmp / "via-link"
    via.symlink_to(plain)               # a linked directory whose settings.json is a file: as written
    empty = tmp / "empty"
    empty.mkdir()                       # no settings.json: as written
    return {linked: home, plain: plain, via: via, empty: empty, home: home}


@pytest.mark.parametrize("which", range(5))
def test_both_twins_give_the_layouts_answer(tmp_path, monkeypatch, which):
    config, expected = list(_layouts(tmp_path).items())[which]
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    want = str(config) if expected == config else os.path.realpath(expected)
    assert str(claude_home.config_home()) == want
    shell = subprocess.run(["bash", "-c", '. "$1" && claude_config_home', "_", str(HOOKS / "lib" / "claude_home.sh")],
                           capture_output=True, text=True, env=dict(os.environ, CLAUDE_CONFIG_DIR=str(config)))
    assert shell.returncode == 0, shell.stderr
    assert shell.stdout.strip() == str(claude_home.config_home())


def test_a_dangling_link_gives_its_targets_directory(tmp_path, monkeypatch):
    """The one input whose answer changed with 0f8ef92ff: a settings.json linking to a file that is gone
    gave the configuration directory (the link test failed); it now gives the directory the link names,
    the same in both twins."""
    config = tmp_path / "dangling"
    config.mkdir()
    (config / "settings.json").symlink_to(tmp_path / "gone-home" / "settings.json")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    assert str(claude_home.config_home()) == os.path.realpath(tmp_path / "gone-home")
    shell = subprocess.run(["bash", "-c", '. "$1" && claude_config_home', "_", str(HOOKS / "lib" / "claude_home.sh")],
                           capture_output=True, text=True, env=dict(os.environ, CLAUDE_CONFIG_DIR=str(config)))
    assert shell.stdout.strip() == os.path.realpath(tmp_path / "gone-home")
