"""Contract tests for shared /dev artifact-chain consumers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXED_ENTRYPOINT = (
    "scripts/resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>"
)
RESULT_FIELDS = (
    "mode",
    "lanes",
    "report_paths",
    "artifact_paths",
    "commit_whitelist_artifacts",
    "qa_inputs",
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_dev_completion_uses_shared_read_only_resolver() -> None:
    text = _read("commands/dev.md")
    section = text[text.index("**Codex-native artifact postcondition") :]

    assert FIXED_ENTRYPOINT in section
    assert 'status == "pass"' in section
    assert "exit 2" in section
    assert "The resolver is read-only" in section
    assert 'mode == "singular"' in section
    assert 'mode == "fanout"' in section
    assert "Never create, copy, or invent" in section
    for field in RESULT_FIELDS:
        assert f"`{field}`" in section


def test_close_resolves_explicit_and_bare_before_singular_assumptions() -> None:
    text = _read("commands/close.md")
    resolution = text[
        text.index("### Task-id resolution") :
        text.index("### do-report lite preflight")
    ]
    flat = _squash(resolution)

    # /close's one chain call is Step 0's selector call, from the harness home.
    assert 'python3 ~/.claude/scripts/close-route-select.py "${ROUTE_SELECT_ARGS[@]}"' in resolution
    assert "both explicit `/close <task-id-or-path>` and bare `/close`" in resolution
    assert "before any parent ticket/context/QA assumption" in resolution
    assert 'PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"' in resolution
    # P1b E5 / ruling 1: the canonical aggregate's one producer is the
    # lane-completeness hook; /close runs no aggregator of its own.
    assert "aggregate-dev-report.py" not in resolution
    assert "runs no aggregator" in flat
    assert "Parent ticket/context/QA are optional" in flat


def test_close_reuses_resolver_for_qa_and_workflow_integrity() -> None:
    text = _read("commands/close.md")
    qa_prompt = text[text.index("### Step 2:") : text.index("### Step 3:")]

    # Report schemas are checked at each producer's stop (G2), not re-run here.
    assert "### Artifact schema gate" not in text
    assert "Lane matrix: <ARTIFACT_CHAIN.lanes" in qa_prompt
    assert "QA inputs: <ARTIFACT_CHAIN.qa_inputs" in qa_prompt
    assert "commit_whitelist_artifacts" in qa_prompt
    assert "WORKFLOW INTEGRITY DIMENSION" in qa_prompt
    assert "parent ticket/context/QA are optional" in qa_prompt
    assert "pseudo-parent" in qa_prompt


def test_normal_commit_and_changelog_share_resolver_whitelist() -> None:
    command = _read("commands/commit.md")
    analyst = _read("agents/changelog-analyst.md")

    assert FIXED_ENTRYPOINT in command
    assert command.count('ARTIFACT_CHAIN="$(python3 ~/.claude/scripts/resolve-dev-artifact-chain.py') == 1
    assert command.index('TASK_PROJECT_ROOT="') < command.index(
        'ARTIFACT_CHAIN="$(python3 ~/.claude/scripts/resolve-dev-artifact-chain.py'
    )
    assert "ARTIFACT_CHAIN=<exact resolver JSON" in command
    assert "ARTIFACT_CHAIN.commit_whitelist_artifacts" in command
    assert FIXED_ENTRYPOINT in analyst
    assert "Every exact path in `ARTIFACT_CHAIN.commit_whitelist_artifacts`" in analyst
    assert "resolver-validated lane ticket/context/dev/QA artifact" in analyst
    assert "Do not glob lane suffixes" in analyst
    assert "original\n+singular overhead" not in analyst
    assert "the original\nsingular overhead" in analyst


def test_close_qa_accepts_one_parent_lane_matrix_without_fake_parents() -> None:
    text = _read("agents/qa.md")
    section = text[
        text.index("**Close-gate lane-matrix exception") :
        text.index("## Input Format")
    ]
    flat = _squash(section)

    assert "one task is the parent closure decision" in flat
    assert "do NOT emit `multi_issue_fanout_requested`" in flat
    for field in RESULT_FIELDS:
        assert f"`{field}`" in section
    assert "parent ticket/context/QA are optional" in flat
    assert "MUST NOT request, create, or pretend" in flat

    # dev-20260914-075954 (M3/AC5): the close-gate lane-matrix exception must
    # be reconciled with the pass_with_exceptions/disclosed_exceptions
    # vocabulary commands/close.md already uses, not the narrower literal
    # status == "pass".
    assert 'status in {"pass", "pass_with_exceptions"}' in section
    assert "`disclosed_exceptions`" in section
    assert "independently re-verify and cite evidence" in flat
    assert "disclosed_exceptions" in flat and "corroborat" in flat
    assert 'status == "pass"' not in section
    # Codex round-1 finding #2: lock the crucial failure semantics themselves
    # (not just the presence of the vocabulary) -- EVERY entry, re-running
    # cited commands rather than re-reading prose, and an uncorroborated
    # entry must fail the parent close.
    assert "for EVERY" in section
    assert "re-running at least the commands" in flat
    assert "cannot be corroborated is a live dissent" in flat
    assert "parent close must fail" in flat


def test_spec_update_consumes_lane_matrix_without_fake_parent_context() -> None:
    text = _read("commands/spec-update.md")
    section = text[
        text.index("## Continuation-spec mode") :
        text.index("## Temp-note mode")
    ]
    flat = _squash(section)

    assert FIXED_ENTRYPOINT in section
    assert "`artifact_paths`, `report_paths`, `qa_inputs`, and" in section
    assert "`lanes[]`" in section
    assert "every lane ticket/context/dev/QA" in flat
    assert "must not create, a parent context" in flat
    assert "fabricate missing parent artifacts" in flat
