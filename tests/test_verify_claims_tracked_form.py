"""scripts/verify-claims.sh verifies the tracked (index) form of settings.json.

On an initialised home the claude-settings filter leaves the machine form in the
working settings.json (an enabled module such as paseo adds hooks), so the
enforcement-evidence step hands the index blob to
scripts/check-enforcement-evidence.py --settings instead. Each case builds a
temporary git repository holding this repository's verify-claims.sh, a
three-entry settings.json staged in the index, and a stub
scripts/check-enforcement-evidence.py that records the --settings content each
mode is handed. In --claims mode the stub derives the hook set with this
repository's real settings_triples() and compares it with a ledger fixture (the
clean settings' hook set), printing the real gate's messages. The hero and
corpus steps have no fixture there and fail on their own lines; the cases assert
only on the enforcement-evidence lines. HOME points at a temporary directory,
GIT_* variables are dropped, the system git config is ignored, and nothing runs
in this repository.
"""

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "verify-claims.sh"
GATE = REPO / "scripts" / "check-enforcement-evidence.py"

CLEAN = {"hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 hooks/pretool-a.py"},
        {"type": "command", "command": "python3 hooks/pretool-b.py"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "bash hooks/stop-c.sh"}]}],
}}
# What a module adds in the machine form: a hook in a new event (4 entries, 3 events).
MACHINE = json.loads(json.dumps(CLEAN))
MACHINE["hooks"]["UserPromptSubmit"] = [
    {"hooks": [{"type": "command", "command": "python3 hooks/userprompt-d.py"}]}]
STUB_GATE = """import importlib.util, os, pathlib, sys
args = sys.argv[1:]
mode = args[0].lstrip("-")
text = open(args[args.index("--settings") + 1], encoding="utf8").read()
handed = pathlib.Path(os.environ["GATE_OUT"], mode)
handed.write_text(text, encoding="utf8")
if mode == "claims":  # like the real gate, only --claims derives the hook set from settings
    spec = importlib.util.spec_from_file_location("gate", os.environ["REAL_GATE"])
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    try:
        derived = gate.settings_triples(str(handed))
        ledger = gate.settings_triples(os.environ["LEDGER_FORM"])
    except gate.Fail as exc:
        print(f"  ERROR: {exc}")
        sys.exit(2)
    for item in sorted(derived - ledger):
        print(f"  FAIL: wired in settings but absent from the ledger: {item}")
    for item in sorted(ledger - derived):
        print(f"  FAIL: present in the ledger but not wired in settings: {item}")
    sys.exit(int(derived != ledger))
"""
CLAIMS_FAIL = "FAIL: enforcement-evidence --claims: see the FAIL lines above"


def _exe(path: Path, body: str):
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write(path: Path, obj):
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=2) + "\n",
                    encoding="utf8")


class Fixture:
    def __init__(self, tmp: Path):
        self.root, self.gate = tmp / "repo", tmp / "gate"
        home, bindir = tmp / "home", tmp / "bin"
        for d in (home, bindir, self.gate, self.root / "scripts"):
            d.mkdir(parents=True)
        _exe(bindir / "python3", f'exec {shlex.quote(sys.executable)} "$@"')
        _exe(bindir / "node", "exit 1")  # never reached: the fixture has no hero assets
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("GIT_") and k != "CLAUDE_CONFIG_DIR"}
        self.env.update(HOME=str(home), PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                        PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1",
                        GIT_CEILING_DIRECTORIES=str(tmp), GATE_OUT=str(self.gate),
                        REAL_GATE=str(GATE), LEDGER_FORM=str(tmp / "ledger-form.json"))
        _write(tmp / "ledger-form.json", CLEAN)  # the hook set the ledger fixture publishes
        shutil.copy2(SCRIPT, self.root / "scripts" / "verify-claims.sh")
        (self.root / "scripts" / "check-enforcement-evidence.py").write_text(STUB_GATE,
                                                                              encoding="utf8")
        _write(self.root / "settings.json", CLEAN)
        self.git("init", "-q")
        self.git("add", "-A")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                       capture_output=True, text=True, timeout=60)

    def stage(self, obj):
        _write(self.root / "settings.json", obj)
        self.git("add", "settings.json")
        return (self.root / "settings.json").read_text(encoding="utf8")

    def verify(self):
        r = subprocess.run(["bash", "scripts/verify-claims.sh"], cwd=self.root, env=self.env,
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 1, r.stdout + r.stderr  # the unfixtured steps always fail
        return r.stdout + r.stderr

    def handed(self, mode):
        return (self.gate / mode).read_text(encoding="utf8")


@pytest.fixture
def fx(tmp_path):
    return Fixture(tmp_path)


def test_machine_form_in_the_working_file_is_not_what_is_verified(fx):
    _write(fx.root / "settings.json", MACHINE)  # unstaged, as the smudge filter leaves it
    out = fx.verify()
    assert json.loads(fx.handed("claims")) == CLEAN
    assert json.loads(fx.handed("ledger")) == CLEAN
    assert "PASS: enforcement-evidence --claims" in out
    assert "PASS: enforcement-evidence --ledger" in out
    assert "FAIL: enforcement-evidence" not in out


def test_a_drift_staged_in_the_index_is_caught(fx):
    fx.stage(MACHINE)
    _write(fx.root / "settings.json", CLEAN)  # the working file no longer shows it
    out = fx.verify()
    assert json.loads(fx.handed("claims")) == MACHINE
    assert ("FAIL: wired in settings but absent from the ledger: "
            "('UserPromptSubmit', '(universal)', 'userprompt-d.py')") in out
    assert CLAIMS_FAIL in out


@pytest.mark.parametrize("staged, reason", [
    ("{ not json\n", "cannot read/parse JSON"),
    ({"permissions": {}}, "'hooks' missing or not a non-empty object"),
    ({"hooks": {"Stop": {}}}, "hooks['Stop'] is not a list"),
    ({"hooks": {"Stop": [{"matcher": ""}]}}, "computed 0 wired hooks"),
    ({"hooks": {"Stop": [{"hooks": []}]}}, "computed 0 wired hooks"),
], ids=["invalid-json", "no-hooks", "event-not-list", "entry-without-hooks", "zero-entries"])
def test_bad_index_content_fails_as_before_even_with_a_valid_working_file(fx, staged, reason):
    text = fx.stage(staged)
    _write(fx.root / "settings.json", CLEAN)
    out = fx.verify()
    assert fx.handed("claims") == text
    assert reason in out
    assert CLAIMS_FAIL in out
    assert "PASS: enforcement-evidence --claims" not in out


@pytest.mark.parametrize("case, reason", [
    ("not-in-index", "exists on disk, but not in the index"),
    ("not-a-repository", "not a git repository"),
], ids=["not-in-index", "not-a-repository"])
def test_no_tracked_settings_fails_and_names_why(fx, case, reason):
    if case == "not-in-index":
        fx.git("rm", "-q", "--cached", "settings.json")
    else:
        shutil.rmtree(fx.root / ".git")
    out = fx.verify()
    assert reason in out
    assert fx.handed("claims") == ""
    assert "cannot read/parse JSON" in out
    assert CLAIMS_FAIL in out
    assert (fx.root / "settings.json").is_file()  # a working file alone is not the tracked form
