"""Complete declared static temp-target mechanism matrix for LANE-B."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
from lib import agent_temp_targets


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("printf x > /tmp/redir", "/tmp/redir"),
        ("printf x >> /tmp/append", "/tmp/append"),
        ("printf x | tee -a /tmp/tee", "/tmp/tee"),
        ("cp source /tmp/cp", "/tmp/cp"),
        ("mv source /tmp/mv", "/tmp/mv"),
        ("install -m 600 source /tmp/install", "/tmp/install"),
        ("rsync -a source /tmp/rsync", "/tmp/rsync"),
        ("ln -s source /tmp/link", "/tmp/link"),
        ("sed -i 's/a/b/' /tmp/sed", "/tmp/sed"),
        ("mkdir -p /tmp/mkdir", "/tmp/mkdir"),
        ("touch /tmp/touch", "/tmp/touch"),
        ("mktemp /tmp/template.XXXX", "/tmp/template.XXXX"),
        ("mktemp --tmpdir=/tmp managed.XXXX", "/tmp"),
        ("truncate -s 0 /tmp/truncate", "/tmp/truncate"),
        ("dd if=/dev/null of=/tmp/dd", "/tmp/dd"),
        ("curl https://example.invalid -o /tmp/curl", "/tmp/curl"),
        ("wget https://example.invalid -O /tmp/wget", "/tmp/wget"),
        ("python -c \"open('/tmp/python','w').write('x')\"", "/tmp/python"),
        ("python -c \"from pathlib import Path; Path('/tmp/pathlib').write_text('x')\"", "/tmp/pathlib"),
        ("node -e \"fs.writeFileSync('/tmp/node','x')\"", "/tmp/node"),
        ("node -e \"fs.mkdirSync('/tmp/node-dir')\"", "/tmp/node-dir"),
    ],
)
def test_declared_mechanism_names_static_destination(command: str, expected: str) -> None:
    analysis = agent_temp_targets.analyze_command(command)
    assert analysis["status"] == "pass"
    assert expected in [item["path"] for item in analysis["targets"]]
    assert analysis["unresolved"] == []


def test_compound_command_reports_every_destination() -> None:
    command = (
        "mkdir /tmp/a && touch /tmp/b; cp x /tmp/c | tee /tmp/d; "
        "dd if=x of=/tmp/e"
    )
    assert set(agent_temp_targets.extract_agent_temp_targets(command)) >= {
        "/tmp/a",
        "/tmp/b",
        "/tmp/c",
        "/tmp/d",
        "/tmp/e",
    }


@pytest.mark.parametrize(
    "command",
    [
        "cp source $TMPDIR/dynamic",
        "mkdir /tmp/$(printf dynamic)",
        "curl https://example.invalid -o ${TARGET}",
        "dd if=/dev/null of=`printf /tmp/dynamic`",
        "mkdir '/tmp/unterminated",
    ],
)
def test_recognized_unresolved_destination_fails_closed_at_seam(command: str) -> None:
    analysis = agent_temp_targets.analyze_command(command)
    assert analysis["unresolved"], analysis
    assert agent_temp_targets.has_unresolved_explicit_temp(command)


def test_bare_mktemp_is_contained_by_managed_environment_not_guessed() -> None:
    analysis = agent_temp_targets.analyze_command("mktemp")
    assert analysis["targets"] == []
    assert analysis["unresolved"] == []
    assert analysis["opaque_runtime_boundary"] is True


def test_opaque_child_boundary_is_explicit_not_a_syscall_claim() -> None:
    analysis = agent_temp_targets.analyze_command("unknown-package-test --no-named-output")
    assert analysis == {
        "status": "pass",
        "targets": [],
        "unresolved": [],
        "parse_ok": True,
        "opaque_runtime_boundary": True,
    }
