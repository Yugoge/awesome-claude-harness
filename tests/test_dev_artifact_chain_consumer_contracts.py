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
    flat = _squash(section)

    assert FIXED_ENTRYPOINT in section
    assert 'status == "pass"' in section
    assert "exit 2" in section
    assert "The resolver is read-only" in section
    assert 'mode == "singular"' in section
    assert 'mode == "fanout"' in section
    assert "parent ticket, context, and QA-report are optional" in flat
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

    assert FIXED_ENTRYPOINT in resolution
    assert "both explicit `/close <task-id-or-path>` and bare `/close`" in resolution
    assert "before any parent ticket/context/QA assumption" in resolution
    assert 'PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"' in resolution
    aggregate = resolution.index("scripts/aggregate-dev-report.py")
    resolver = resolution.index("scripts/resolve-dev-artifact-chain.py")
    assert aggregate < resolver
    assert "creates a missing canonical aggregate" in resolution
    assert "sole permitted close-time artifact repair" in resolution
    assert "Parent ticket/context/QA are optional" in flat


def test_close_reuses_resolver_for_schema_qa_and_workflow_integrity() -> None:
    text = _read("commands/close.md")
    schema = text[text.index("### Artifact schema gate") : text.index("### Step 1:")]
    qa_prompt = text[text.index("### Step 2:") : text.index("### Step 3:")]

    assert "ARTIFACT_CHAIN.report_paths[]" in schema
    assert '"report_paths"' in schema
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
    assert command.count('ARTIFACT_CHAIN="$(python3 scripts/resolve-dev-artifact-chain.py') == 1
    assert command.index('TASK_PROJECT_ROOT="') < command.index(
        'ARTIFACT_CHAIN="$(python3 scripts/resolve-dev-artifact-chain.py'
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


# ---------------------------------------------------------------------------
# Third shape: explicit artifact-chain declaration (task 20260803-150741).
# Every assertion below is ADDITIVE; no pre-existing literal was reworded.
# ---------------------------------------------------------------------------

PARALLEL_DEV_MODE = 'mode == "parallel_dev"'


def test_dev_documents_the_declaration_schema_and_creation_interface() -> None:
    text = _read("commands/dev.md")

    assert "artifact_chain_declaration" in text
    assert '"version"' in text
    assert '"parallel_dev"' in text and '"requirement_fanout"' in text
    assert "declared_lanes" in text
    assert "--shape parallel_dev" in text
    assert "--shape requirement_fanout" in text
    assert "--declared-lanes" in text
    assert "closed enum" in _squash(text).lower()
    assert "absence NEVER grants the lax shape" in _squash(text)


def test_dev_derives_shape_and_roster_at_decomposition_time() -> None:
    flat = _squash(_read("commands/dev.md"))

    assert "`len(requirements[]) > 1`" in flat
    assert "`requirement_fanout` — always; never downgradable" in flat
    assert "N > 1 implementation workers dispatched at Step 10" in flat
    assert "set(declared_lanes) == {lane suffix of r for r in requirements[]}" in flat
    assert "len(declared_lanes) == len(requirements)" in flat
    assert "no omissions and no duplicates" in flat
    assert "For the `parallel_dev` shape the roster is EMPTY" in flat
    assert "ONLY sanctioned write path for the declaration" in flat
    assert (
        "chosen at decomposition time and may be neither inferred nor "
        "downgraded at aggregation time"
    ) in flat
    # The residual is stated honestly; no detection claim is made.
    assert "only when the omitted lane produced literally nothing" in flat
    assert "CANNOT detect a decomposition-time roster truncation" in flat


def test_dev_completion_postcondition_admits_the_parallel_dev_shape() -> None:
    text = _read("commands/dev.md")
    section = text[text.index("**Codex-native artifact postcondition") :]
    flat = _squash(section)

    # Pre-existing literals stay intact.
    assert 'mode == "singular"' in section
    assert 'mode == "fanout"' in section
    assert PARALLEL_DEV_MODE in section
    assert "Per-worker ticket, context, and QA-report are NOT required" in flat
    assert "MUST NOT be fabricated, retro-declared, or copied" in flat


def test_mode_sensitive_consumers_admit_the_parallel_dev_shape() -> None:
    analyst = _read("agents/changelog-analyst.md")
    assert "{singular, fanout, parallel_dev}" in analyst
    assert "never as `foreign_session_candidate`" in _squash(analyst)

    close = _read("commands/close.md")
    parallel = close[close.index("**Parallel detection check**") :]
    parallel = parallel[: parallel.index("**If a parallel cycle is detected**")]
    assert 'ARTIFACT_CHAIN.mode == "fanout"' in parallel
    assert 'ARTIFACT_CHAIN.mode == "parallel_dev"' in parallel

    qa_text = _read("agents/qa.md")
    section = qa_text[
        qa_text.index("**Close-gate lane-matrix exception") : qa_text.index("## Input Format")
    ]
    flat = _squash(section)
    assert PARALLEL_DEV_MODE in section
    assert "`lanes` is legitimately EMPTY" in flat
    assert "do NOT emit `multi_issue_fanout_requested`" in flat

    spec_update = _read("commands/spec-update.md")
    section = spec_update[
        spec_update.index("## Continuation-spec mode") : spec_update.index("## Temp-note mode")
    ]
    flat = _squash(section)
    assert "`parallel_dev` mode" in flat
    assert "every per-worker dev-report named in `report_paths`" in flat
    assert "do not invent lane contexts or a parent context" in flat
