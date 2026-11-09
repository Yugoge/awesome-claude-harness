"""The replay's orchestrator takes a dispatch template's role from its obligation block (P6-4).

The role a template dispatches is its subagent_type, else the role of the obligation block it
instantiates, read with the tree's own grammar (hooks/lib/obligation.py's extract_obligation_block,
the block the hooks read). Neither the FIRST ACTION sentinel line nor the sentinel's file name
decides it (D21: no filename-to-role table). These run on this checkout's own commands/dev.md and
hooks/lib, with no sandbox: the tree is read, nothing is run.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import subprocess
import sys
import tarfile
import types
from pathlib import Path

import pytest

from tests.replay import agents, cmdtext
from tests.replay.pipeline import Orchestrator
from tests.replay.test_live_landing import TRANSITIONS

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = re.compile(r"(FIRST ACTION: Read \S*/\.claude/dev-registry/[^/\s]+/)([A-Za-z0-9_-]+)(\.json)")


class _RP:
    """The little of a replay process the orchestrator's text reads touch."""

    def __init__(self, project: Path, harness: Path = ROOT):
        self.layout = types.SimpleNamespace(harness=str(harness), project=str(project))

    @contextlib.contextmanager
    def acting(self, role):
        yield


@pytest.fixture
def dev(tmp_path) -> Orchestrator:
    return Orchestrator(_RP(tmp_path), "dev", session=object())


def _templates(o: Orchestrator, heading: str) -> list[dict]:
    out, k = [], 0
    while True:
        try:
            out.append(o.template(heading, index=k))
        except cmdtext.TextNotFound:
            return out
        k += 1


def _sentinel_role(prompt: str) -> str | None:
    m = SENTINEL.search(prompt)
    return m.group(2) if m else None


def _renamed(fields: dict, role: str) -> dict:
    """The template with its FIRST ACTION sentinel naming `role` instead."""
    prompt, n = SENTINEL.subn(lambda m: m.group(1) + role + m.group(3), fields["prompt"])
    assert n == 1, "the template has one FIRST ACTION sentinel line"
    return dict(fields, prompt=prompt)


def test_sentence_template_role_is_its_obligation_not_its_first_action(dev):
    """Step 10's dev and test-writer templates spell their obligation as the "embed ... here with
    role=..." sentence. With the FIRST ACTION sentinel naming another role, each still resolves to
    its obligation's role."""
    found = {}
    for t in _templates(dev, "Step 10"):
        assert not t.get("subagent_type"), "the Step 10 templates name no subagent_type"
        role = dev.template_role(t, "20260101-000000")
        found[role] = t
        assert role == _sentinel_role(t["prompt"])  # the shipped text: both say the same
        other = "qa" if role != "qa" else "dev"
        assert dev.template_role(_renamed(t, other), "20260101-000000") == role
    assert set(found) == {"dev", "test-writer"}


def test_literal_block_template_role_is_its_obligation_not_its_first_action(dev):
    """Step 4's BA template carries a literal worked-example block (role "ba")."""
    ba = next(t for t in _templates(dev, "Step 4") if not t.get("subagent_type"))
    assert dev.template_role(ba, "20260101-000000") == "ba"
    assert dev.template_role(_renamed(ba, "qa"), "20260101-000000") == "ba"


def test_rendered_prompt_role_is_its_obligation_block(dev):
    """The rendered dispatch prompt (what dispatch() reads its subagent_type from): the obligation's
    role, whatever the FIRST ACTION sentinel names; no block names no role, the sentinel does not."""
    t = next(t for t in _templates(dev, "Step 10") if dev.template_role(t, "x") == "dev")
    prompt = dev.instantiate(_renamed(t, "qa")["prompt"], "20260101-000000")
    assert _sentinel_role(prompt) == "qa"
    assert dev.tree.obligation_role(prompt) == "dev"
    no_block = re.sub(r'<obligation v="1">.*?</obligation>\n?', "", prompt, flags=re.S)
    assert _sentinel_role(no_block) == "qa"
    assert dev.tree.obligation_role(no_block) is None
    assert dev.template_role(dict(t, prompt=no_block)) is None
    two = prompt + "\n" + prompt[prompt.index('<obligation v="1">'):prompt.index("</obligation>") + 13]
    assert dev.tree.obligation_role(two) is None  # the hooks' grammar: more than one block is no block


def test_subagent_type_still_wins(dev):
    t = next(t for t in _templates(dev, "Step 10") if dev.template_role(t, "x") == "dev")
    assert dev.template_role(dict(t, subagent_type="test-writer"), "x") == "test-writer"


def test_no_orchestrator_site_reads_the_sentinel_for_a_role():
    """The replay's orchestrator side (pipeline and the drivers) no longer derives a role from the
    FIRST ACTION line; only the simulated agent's own brief keeps its sentinel reader."""
    here = ROOT / "tests" / "replay"
    users = sorted(str(p.relative_to(here)) for p in [here / "pipeline.py", *(here / "drivers").glob("*.py")]
                   if "registry_role" in p.read_text(encoding="utf-8"))
    assert users == []
    assert agents.registry_role("FIRST ACTION: Read /p/.claude/dev-registry/s/qa.json.") == "qa"


def test_an_old_trees_obligation_module_loads(tmp_path):
    """The replay plays old trees too (test_live_landing's master, 2acc29b). That tree's
    obligation.py defines dataclasses, which look their module up in sys.modules while the class
    is made: run from its file without being registered there it does not load, and every role
    read on that tree failed. The tree's own file loads, and its own grammar names the role."""
    sha = TRANSITIONS["master"]
    tar = subprocess.run(["git", "-C", str(ROOT), "archive", sha, "hooks/lib"], capture_output=True, check=True)
    tree = tmp_path / "tree"
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as tf:
        tf.extractall(tree, filter="data")
    path = tree / "hooks" / "lib" / "obligation.py"
    assert "@dataclass" in path.read_text(encoding="utf-8"), "the old tree's module is the dataclass one"
    # The failure the loader avoids: the same file run unregistered does not load.
    spec = importlib.util.spec_from_file_location("p64_unregistered_obligation", path)
    with pytest.raises(AttributeError):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert "p64_unregistered_obligation" not in sys.modules

    t = agents.Tree(_RP(tmp_path, harness=tree))
    mod = t.obligation()
    assert mod is not None and Path(mod.__file__) == path
    assert t.obligation() is mod  # loaded once
    prompt = ("FIRST ACTION: Read /p/.claude/dev-registry/s/qa.json to register.\n"
              '<obligation v="1">\n{"task_id": "20260101-000000", "role": "dev", "pipeline": "dev"}\n</obligation>\n')
    assert t.obligation_role(prompt) == "dev"
    assert t.obligation_role(prompt.split("<obligation")[0]) is None
