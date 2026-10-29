"""Readers that take a set from its declaration instead of a copy of it
(P1b row 19 rule 7): the chain resolver's disclosed-exception
classifications are schemas/qa-report.v1.json's enum, and the orphan-agent
detector asks the command files whether they name an agent instead of
keeping a list of agents it excuses.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _resolver():
    spec = importlib.util.spec_from_file_location("resolve_dev_artifact_chain",
                                                  REPO / "scripts" / "resolve-dev-artifact-chain.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_disclosed_exception_classifications_are_the_schemas():
    schema = json.loads((REPO / "schemas" / "qa-report.v1.json").read_text(encoding="utf-8"))
    declared = schema["properties"]["disclosed_exception"]["properties"]["classification"]["enum"]
    resolver = _resolver()
    assert resolver._qa_disclosed_classifications() == frozenset(declared)
    report = {"iteration_needed": False, "qa": {"disclosed_exception": {
        "classification": declared[0], "evidence": ["shared tree"],
        "attestation": resolver.DISCLOSED_EXCEPTION_ATTESTATION}}}
    assert resolver._qa_environmental_eligible(report)
    report["qa"]["disclosed_exception"]["classification"] = "not_declared"
    assert not resolver._qa_environmental_eligible(report)


def test_an_agent_no_command_names_is_the_only_orphan(tmp_path):
    home = tmp_path / "harness"
    (home / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "detect-orphan-agents.sh", home / "scripts")
    (home / "agents").mkdir()
    (home / "commands").mkdir()
    for name in ("cleaner", "graphify", "triage-helper", "lonely-analyst"):
        (home / "agents" / f"{name}.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    (home / "agents" / "INDEX.md").write_text("cleaner graphify lonely-analyst\n", encoding="utf-8")
    (home / "commands" / "clean.md").write_text("Invoke the cleaner subagent using the Agent tool.\n",
                                                encoding="utf-8")
    (home / "commands" / "dev.md").write_text('- subagent_type: "graphify"\nDelegate to triage-helper subagent.\n',
                                              encoding="utf-8")
    # The commands' own index names every agent; it dispatches none.
    (home / "commands" / "INDEX.md").write_text("lonely-analyst\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    run = subprocess.run(["bash", str(home / "scripts" / "detect-orphan-agents.sh"), str(project)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    found = json.loads(run.stdout)
    assert [Path(o["file"]).name for o in found["orphan_agents"]] == ["lonely-analyst.md"]
    assert found["summary"]["total"] == 1
