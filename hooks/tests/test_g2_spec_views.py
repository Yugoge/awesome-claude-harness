"""G2's spec-view check (P1b row 8): a /spec split is checked at the spec
subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
(`spec_views`), the rule moved out of stop-spec-coverage-enforce.py. A spec
subagent dispatched from the base's /spec template carries no obligation; G2
takes the rule the current commands/spec.md template declares for its
subagent_type (hooks/lib/dispatch_template.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "subagentstop-artifact-contract-enforce.py"
sys.path.insert(0, str(REPO / "hooks" / "lib"))
import dispatch_template  # noqa: E402

SPEC_ID = "20261028-101010"
MONOLITH = f"docs/dev/specs/spec-{SPEC_ID}.md"
VIEWS = f"docs/dev/specs/{SPEC_ID}/views"
SESSION = "11111111-2222-3333-4444-555555555555"
AGENT = "a0123456789abcdef"
TOOL_USE = "toolu_spec_dispatch_1"

MONO_TEXT = """# Spec: toy

## Section 5: User's Acceptance Criterion

Make add return the sum of two numbers.
Keep sub unchanged for callers.
The toy tests must pass.
Report the pytest result line.
"""
HEADER = "<!-- AUTO-GENERATED VIEW for {a} | source: m | extracted: now -->\n\n# {a} view of x\n\n**Monolith**: m\n\n---\n\n"
VIEW_TEXT = {
    "ba.md": HEADER.format(a="ba") + "## Role Mandate\n\n> Make add return the sum of two numbers.\n\n"
             "Make add return the sum of two numbers.\nKeep sub unchanged for callers.\n",
    "qa.md": HEADER.format(a="qa") + "## Role Mandate\n\n> The toy tests must pass.\n\n"
             "The toy tests must pass.\nReport the pytest result line.\n",
    "orchestrator.md": HEADER.format(a="orchestrator") + "## Role Mandate (from spec)\n\n"
                       "> Make add return the sum of two numbers.\n\n## Pipeline Workflow\n\n# Spec: toy\n"
                       "## Section 5: User's Acceptance Criterion\n",
}


def _split(project: Path, complete: bool, mono: str = MONO_TEXT, view_text: dict = VIEW_TEXT,
           manifest: dict | None = None) -> None:
    (project / MONOLITH).parent.mkdir(parents=True, exist_ok=True)
    (project / MONOLITH).write_text(mono, encoding="utf-8")
    views = project / VIEWS
    views.mkdir(parents=True, exist_ok=True)
    for name, text in view_text.items():
        if not complete and name == "qa.md":
            text = text.replace("Report the pytest result line.\n", "")
        (views / name).write_text(text, encoding="utf-8")
    # The manifest the spec subagent writes (agents/spec.md Step 5): the views it wrote, of this monolith.
    if manifest is None:
        manifest = {"schema_version": 1, "spec_id": SPEC_ID, "monolith_path": MONOLITH,
                    "views": {n[:-3]: f"views/{n}" for n in view_text if n != "orchestrator.md"}}
    if manifest:
        (views / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _base_prompt(project: Path) -> str:
    # The base's /spec Step 6 template, instantiated: no obligation block.
    return (
        "You are the spec subagent. Read and follow the instructions in ~/.claude/agents/spec.md EXACTLY.\n"
        f"Spec id: {SPEC_ID}\nMonolith: {project / MONOLITH}\nMonolith lines: 8\n"
        f"Output folder: docs/dev/specs/{SPEC_ID}/\nProject dir: {project}\n"
        "Execute Phase 0 (read spec, decide relevant agents).\n"
    )


def _obligation_prompt(project: Path) -> str:
    doc = {"task_id": SPEC_ID, "lane": None, "lane_set": None, "role": "spec", "pipeline": "spec",
           "profile": "singular", "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "artifacts": [{"kind": "spec_views", "path": VIEWS, "monolith": MONOLITH}]}
    return _base_prompt(project) + f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>\n'


def _store(home: Path, project: Path, prompt: str, subagent_type: str | None) -> None:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))  # Claude Code's folder name
    session_dir = home / ".claude" / "projects" / slug / SESSION
    (session_dir / "subagents").mkdir(parents=True, exist_ok=True)
    agent = session_dir / "subagents" / f"agent-{AGENT}.jsonl"
    agent.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n",
                     encoding="utf-8")
    agent.with_name(agent.stem + ".meta.json").write_text(json.dumps({"toolUseId": TOOL_USE}), encoding="utf-8")
    tool_input = {"description": "Spec agent", "prompt": prompt}
    if subagent_type:
        tool_input["subagent_type"] = subagent_type
    parent = [
        {"type": "user", "message": {"role": "user", "content": "/spec make add work"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": TOOL_USE, "name": "Agent", "input": tool_input}]}},
    ]
    (session_dir.parent / f"{SESSION}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in parent),
                                                        encoding="utf-8")


def _stop(tmp_path: Path, prompt_of, subagent_type="spec", complete=True, mode="block", **split):
    project, home = tmp_path / "project", tmp_path / "home"
    project.mkdir(parents=True, exist_ok=True)
    _split(project, complete, **split)
    _store(home, project, prompt_of(project), subagent_type)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_OBLIGATION_STOPGATE": mode}
    payload = {"agent_id": AGENT, "session_id": SESSION, "agent_type": subagent_type or "general-purpose"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=60)


def test_declared_split_that_passes_spec_verify_strict_stops(tmp_path):
    run = _stop(tmp_path, _obligation_prompt)
    assert run.returncode == 0, run.stderr


def test_declared_split_that_fails_spec_verify_strict_goes_back_to_the_spec_subagent(tmp_path):
    run = _stop(tmp_path, _obligation_prompt, complete=False)
    assert run.returncode == 2, run.stderr
    assert "OBLIGATION_STOPGATE_BLOCKED" in run.stderr
    assert f"{VIEWS}: spec_verify_strict_failed" in run.stderr
    assert re.search(r"coverage:\s+FAIL \(\d+\.\d% < 100\.0%\)", run.stderr)  # the failing row, not a tail


def test_a_view_lacking_a_role_mandate_the_monolith_annotates_is_named_with_the_section(tmp_path):
    qa = HEADER.format(a="qa") + "### Role: qa\n\nThe toy tests must pass.\nReport the pytest result line.\n"
    run = _stop(tmp_path, _obligation_prompt, mono=MONO_TEXT + "\n### Role: qa\n",
                view_text=dict(VIEW_TEXT, **{"qa.md": qa}))
    assert run.returncode == 2, run.stderr
    assert re.search(r"structural:\s+FAIL \(qa\.md: ## Role Mandate missing\)", run.stderr), run.stderr
    # Without the annotation R3.4 lets the view omit the section: nothing blocks.
    assert _stop(tmp_path / "plain", _obligation_prompt, view_text=dict(VIEW_TEXT, **{"qa.md": qa})).returncode == 0


def test_advisory_mode_never_blocks(tmp_path):
    run = _stop(tmp_path, _obligation_prompt, complete=False, mode="advisory")
    assert run.returncode == 0, run.stderr


def test_a_base_template_dispatch_is_checked_by_the_current_template_rule(tmp_path):
    run = _stop(tmp_path, _base_prompt, complete=False)
    assert run.returncode == 2, run.stderr
    assert f"{VIEWS}: spec_verify_strict_failed" in run.stderr
    assert _stop(tmp_path / "ok", _base_prompt).returncode == 0


def test_a_dispatch_of_a_type_no_current_template_declares_is_not_checked(tmp_path):
    run = _stop(tmp_path, _base_prompt, subagent_type=None, complete=False)
    assert run.returncode == 0, run.stderr


def test_the_current_spec_template_declares_the_split_bound_to_the_dispatch(tmp_path):
    project = tmp_path / "project"
    declared = dispatch_template.template_obligation("spec", "spec", _base_prompt(project))
    assert declared["role"] == "spec" and declared["pipeline"] == "spec" and declared["task_id"] == SPEC_ID
    assert declared["artifacts"] == [{"kind": "spec_views", "path": VIEWS, "monolith": MONOLITH}]
    assert dispatch_template.template_obligation("spec", "general-purpose", _base_prompt(project)) is None
    assert dispatch_template.template_obligation("spec", "spec", "no matching lines") is None


def test_the_spec_views_grammar_in_the_library_and_the_schema():
    import jsonschema

    sys.path.insert(0, str(REPO / "hooks"))
    from lib import obligation

    doc = {"task_id": SPEC_ID, "lane": None, "lane_set": None, "role": "spec", "pipeline": "spec",
           "profile": "singular", "dispatched_at": "2026-10-28T10:10:10Z",
           "artifacts": [{"kind": "spec_views", "path": VIEWS, "monolith": MONOLITH}]}
    schema = json.loads((REPO / "schemas" / "obligation.v1.json").read_text(encoding="utf-8"))
    assert isinstance(obligation.validate_obligation(doc), obligation.Validated)
    jsonschema.Draft7Validator(schema).validate(doc)
    for bad in ({"kind": "spec_views", "path": VIEWS, "monolith": "/abs/spec.md"},
                {"kind": "spec_views", "path": VIEWS}):
        rejected = obligation.validate_obligation(dict(doc, artifacts=[bad]))
        assert isinstance(rejected, obligation.Rejection), bad
        assert not jsonschema.Draft7Validator(schema).is_valid(dict(doc, artifacts=[bad]))


@pytest.mark.parametrize("manifest, failed", [
    ({}, "views/manifest.json missing or not a regular file"),
    ({"schema_version": 1, "spec_id": SPEC_ID, "monolith_path": "docs/dev/specs/other.md",
      "views": {"ba": "views/ba.md"}}, "points at a non-existent file"),
    ({"schema_version": 1, "spec_id": SPEC_ID, "monolith_path": MONOLITH,
      "views": {"ba": "views/ba.md", "dev": "views/dev.md"}}, "referenced view file for role 'dev' not found"),
], ids=["missing", "other_monolith", "view_missing"])
def test_the_splits_manifest_is_checked_at_the_spec_subagents_stop(tmp_path, manifest, failed):
    """P1b E4: the split's own manifest predicates (resolve-spec-artifacts.py split_problem, the rule
    /spec's finalize guard ran in the orchestrator's call, which spec-verify.py --project-dir applies)
    go back to the spec subagent at its stop, naming the manifest and the failed predicate; the
    marker the orchestrator writes later is not among them."""
    run = _stop(tmp_path, _obligation_prompt, manifest=manifest)
    assert run.returncode == 2, run.stderr
    assert f"{VIEWS}: spec_verify_strict_failed" in run.stderr
    assert re.search(rf"split:\s+FAIL \({re.escape(VIEWS)}/manifest\.json: ", run.stderr), run.stderr
    assert failed in run.stderr


def _hashed(mono: str = MONO_TEXT) -> dict:
    """The manifest agents/spec.md Step 5 writes: the views and the monolith's sha256."""
    return {"schema_version": 1, "spec_id": SPEC_ID, "monolith_path": MONOLITH,
            "sha256": hashlib.sha256(mono.encode("utf-8")).hexdigest(),
            "views": {n[:-3]: f"views/{n}" for n in VIEW_TEXT if n != "orchestrator.md"}}


def test_a_stale_split_goes_back_to_the_spec_subagent(tmp_path):
    """P1b E4: the split's freshness, a rule /spec's finalize guard ran with the resolver after the
    marker: a manifest whose recorded monolith hash is not the monolith's goes back to the spec
    subagent naming the manifest and the failed predicate. The same split with its hash stops with
    no marker yet (/spec writes it after this stop), and with a marker under the monolith's prefixed
    id, a file the spec subagent neither wrote nor may remove (the consumers' resolver rejects it)."""
    assert _stop(tmp_path / "ok", _obligation_prompt, manifest=_hashed()).returncode == 0
    stray = tmp_path / "misplaced" / "project" / f"docs/dev/specs/spec-{SPEC_ID}" / ".split-complete"
    stray.parent.mkdir(parents=True)
    stray.write_text("split-complete: 2026-10-28T10:10:10+00:00\n", encoding="utf-8")
    assert _stop(tmp_path / "misplaced", _obligation_prompt, manifest=_hashed()).returncode == 0
    run = _stop(tmp_path, _obligation_prompt, manifest=_hashed(MONO_TEXT + "Section 7 changed.\n"))
    assert run.returncode == 2, run.stderr
    assert re.search(rf"split:\s+FAIL \({re.escape(VIEWS)}/manifest\.json: ", run.stderr), run.stderr
    assert "split is stale (monolith content changed since split: manifest sha256 != monolith hash)" in run.stderr



def _aged_stop(tmp_path: Path, prompt_of, aged: dict, earlier_seconds: float | None = None):
    """_stop with some view files' mtimes set back (name -> seconds before now) and, with
    ``earlier_seconds``, an earlier dispatch of the same /spec template in the parent transcript
    (a split-QA re-split round: /spec Step 6 re-invokes the spec subagent, which re-extracts only
    the affected views)."""
    project, home = tmp_path / "project", tmp_path / "home"
    project.mkdir(parents=True, exist_ok=True)
    _split(project, True)
    for name, seconds in aged.items():
        then = datetime.now(timezone.utc).timestamp() - seconds
        os.utime(project / VIEWS / name, (then, then))
    prompt = prompt_of(project)
    _store(home, project, prompt, "spec")
    if earlier_seconds is not None:
        when = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - earlier_seconds, tz=timezone.utc)
        first = re.sub(r'"dispatched_at": "[^"]*"', f'"dispatched_at": "{when.strftime("%Y-%m-%dT%H:%M:%SZ")}"',
                       prompt)
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))  # Claude Code's folder name (P6)
        parent = home / ".claude" / "projects" / slug / f"{SESSION}.jsonl"
        call = {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_spec_dispatch_0", "name": "Agent",
             "input": {"description": "Spec agent", "prompt": first, "subagent_type": "spec"}}]}}
        lines = parent.read_text(encoding="utf-8").splitlines(keepends=True)
        parent.write_text(lines[0] + json.dumps(call) + "\n" + "".join(lines[1:]), encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_OBLIGATION_STOPGATE": "block"}
    payload = {"agent_id": AGENT, "session_id": SESSION, "agent_type": "spec"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=60)


def test_a_view_older_than_the_dispatch_goes_back_to_the_spec_subagent(tmp_path):
    """P1b E4: a view the split's dispatch did not write (mtime an hour before its dispatched_at)
    passes spec-verify on content, and is stopped by the freshness rule, naming the view."""
    run = _aged_stop(tmp_path, _obligation_prompt, {"qa.md": 3600})
    assert run.returncode == 2, run.stderr
    assert f"  - {VIEWS}/qa.md: artifact_stale" in run.stderr, run.stderr
    assert f"{VIEWS}/ba.md: artifact_stale" not in run.stderr
    assert "spec_verify_strict_failed" not in run.stderr


def test_a_re_split_keeps_the_views_its_first_round_wrote(tmp_path):
    # Round 1 dispatched 20 minutes ago wrote ba.md; the re-split re-extracted only qa.md.
    assert _aged_stop(tmp_path, _obligation_prompt, {"ba.md": 600}, earlier_seconds=1200).returncode == 0
    run = _aged_stop(tmp_path / "older", _obligation_prompt, {"ba.md": 3600}, earlier_seconds=1200)
    assert run.returncode == 2 and f"{VIEWS}/ba.md: artifact_stale" in run.stderr, run.stderr


def test_a_base_template_dispatch_has_no_dispatched_at_to_be_stale_against(tmp_path):
    # The base's /spec text declares no obligation: the current template's rule binds no
    # dispatched_at, so freshness is undecided and blocks nothing.
    assert _aged_stop(tmp_path, _base_prompt, {"qa.md": 3600}).returncode == 0


def test_the_stop_coverage_hook_is_an_exit_zero_stub(tmp_path):
    """P1b row 8, Correction 9: stop-spec-coverage-enforce.py, which the Stop coordinator runs as
    its coverage phase, allows the /spec orchestrator's Stop on a split spec-verify rejects (the
    stop it blocked before): the rule is G2's at the spec subagent's stop, above."""
    stub = REPO / "hooks" / "stop-spec-coverage-enforce.py"
    assert any(line.startswith("# STUB:") for line in stub.read_text(encoding="utf-8").splitlines())
    project = tmp_path / "project"
    _split(project, complete=False)
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "/spec x"}}) + "\n",
                          encoding="utf-8")
    payload = {"session_id": SESSION, "transcript_path": str(transcript), "stop_hook_active": False}
    run = subprocess.run([sys.executable, str(stub)], input=json.dumps(payload), text=True, capture_output=True,
                         env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)}, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")

