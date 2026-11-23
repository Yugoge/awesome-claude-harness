"""The Stop gate's one scan is opened on the chain's copy of obligation without loading the chain script."""

import importlib
import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

_spec = importlib.util.spec_from_file_location("stop_command_gate_under_test", HOOKS / "stop-command-gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

CHAIN = "scripts/resolve-dev-artifact-chain.py"


def test_opening_the_scan_does_not_load_the_chain_script(monkeypatch):
    monkeypatch.setattr(gate, "_SCRIPTS", {})
    obligation = importlib.import_module("hooks.lib.obligation")
    with gate._one_scan():
        assert obligation._SCAN is not None  # the scan is on the copy the chain imports
        assert CHAIN not in gate._SCRIPTS    # and the chain script, a decider of its own, is not loaded for it
    assert obligation._SCAN is None
