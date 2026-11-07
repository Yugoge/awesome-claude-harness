"""Contract tests for shared /dev artifact-chain consumers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXED_ENTRYPOINT = (
    "scripts/resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>"
)
# the same entrypoint as a command runs it, from the harness home (P2 R6)
FIXED_ENTRYPOINT_RUN = (
    'python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/resolve-dev-artifact-chain.py"'
    " --task-id <id> --project-dir <root>"
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
    step0 = text[text.index("### Step 0:") : text.index("### Routes")]
    flat = _squash(step0)

    # /close's one chain call is Step 0's disposition call, from the harness
    # home (P4 R1); Steps 1-3 read the chain's data fields from that run (R3).
    assert text.count("resolve-dev-artifact-chain.py --disposition") == 1
    assert (
        'python3 "${CLAUDE_HOME:-$HOME/.claude}"/scripts/resolve-dev-artifact-chain.py'
        ' --disposition --stage dev --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"'
    ) in step0
    assert "close-route-select" not in text
    assert "explicit and bare `/close` alike" in flat
    assert "no parent ticket/context/QA assumption before it" in flat
    assert "`CHAIN=<JSON>`" in step0
    for field in RESULT_FIELDS:
        assert f"`{field}`" in step0
    # P1b E5 / ruling 1: the canonical aggregate's one producer is the
    # lane-completeness hook; /close runs no aggregator of its own.
    assert "aggregate-dev-report.py" not in text
    assert "runs no aggregator" in flat
    assert "Parent ticket/context/QA are optional" in flat


def test_close_reuses_resolver_for_qa_and_workflow_integrity() -> None:
    text = _read("commands/close.md")
    qa_prompt = text[text.index("### Step 2:") : text.index("### Step 3:")]

    # Report schemas are checked at each producer's stop (G2), not re-run here,
    # and QA cites Step 0's chain_pass instead of re-checking the chain (R3).
    assert "### Artifact schema gate" not in text
    assert "_exceptions" not in text
    assert "- Disposition: chain_pass" in qa_prompt
    assert "Step 0's `chain_pass`" in qa_prompt
    assert "Lane matrix: <ARTIFACT_CHAIN.lanes" in qa_prompt
    assert "QA inputs: <ARTIFACT_CHAIN.qa_inputs" in qa_prompt
    assert "commit_whitelist_artifacts" in qa_prompt
    assert "WORKFLOW INTEGRITY DIMENSION" in qa_prompt
    assert "parent ticket/context/QA are optional" in qa_prompt
    assert "pseudo-parent" in qa_prompt


def test_normal_commit_and_changelog_share_resolver_whitelist() -> None:
    command = _read("commands/commit.md")
    analyst = _read("agents/changelog-analyst.md")
    step3 = command[command.index("### Step 3:") : command.index("### Step 4:")]

    # P4 R5: /commit's one chain call is Step 3's disposition at the close stage; its
    # CHAIN line is the data Step 5 and Step 7 hand on, never a second call.
    assert command.count("resolve-dev-artifact-chain.py --disposition") == 1
    assert "resolve-dev-artifact-chain.py --disposition --stage close" in step3
    assert "--bulk" not in step3.split("```bash")[1].split("```")[0]
    assert "resolve-dev-artifact-chain.py --task-id" not in command
    assert 'ARTIFACT_CHAIN="$(' not in command
    assert "`CHAIN=` line" in step3 and "No second chain call is made." in step3
    assert "ARTIFACT_CHAIN=<the chain data fields of Step 3's disposition call" in command
    assert "ARTIFACT_CHAIN.commit_whitelist_artifacts" in command
    assert "Every exact path in `ARTIFACT_CHAIN.commit_whitelist_artifacts`" in analyst
    assert "resolver-validated lane ticket/context/dev/QA artifact" in analyst
    assert "Do not glob lane suffixes" in analyst
    assert "original\n+singular overhead" not in analyst
    assert "the original\nsingular overhead" in analyst


def test_commit_completes_an_unclosed_task_from_one_disposition() -> None:
    """P4 R5: an incomplete disposition is completed (dev-stage gaps routed, the close
    stage as close.md Steps 1-2), the waits are in-turn questions, nothing re-validates."""
    command = _read("commands/commit.md")
    step3 = command[command.index("### Step 3:") : command.index("### Step 4:")]
    flat = _squash(step3)

    assert "route it (Routes)" in flat
    assert "run `commands/close.md` Steps 1-2 for this task id" in flat
    assert "OPERATION_STALLED: <the error>" in flat
    # D10 (--dry-run): the cycle completes first; no close-gate relaxation is left.
    assert "`--dry-run` completes the cycle here exactly as a real run does" in flat
    assert "DRYRUN" not in step3 and "check 2 relaxed" not in command
    # Check 3 stays advisory; checks 1, 2 and 4 are the disposition.
    assert "Check 3 — close-report age (advisory, never aborts)" in step3
    assert "check 4" not in command.lower() and "FORCED" not in command
    for gone in ("AWAITING_INPUT", "awaiting-input", "R15", "arbitrat", "route_finding", "owing_dispatch",
                 "pass_with_exceptions", "artifact_role", "source_check"):
        assert gone not in command, gone
    # Each wait is one AskUserQuestion with a header of at most 12 characters.
    headers = __import__("re").findall(r"header `([^`]+)`", command)
    assert sorted(headers) == ["Authorize", "Flags", "Request", "Task"], headers
    assert all(len(h) <= 12 for h in headers)
    assert "/stop" not in command and "I will fix the harness" not in command
    related = command[command.index("## Related") :]
    assert "may run first; `/commit` completes an unclosed task itself" in related


def test_changelog_analyst_phase1_takes_the_chain_as_data() -> None:
    """P4 R6: Phase 1 validates the repository plan, not ARTIFACT_CHAIN; a late-repair
    effective report the plan names is still admitted."""
    analyst = _read("agents/changelog-analyst.md")
    phase1 = analyst[analyst.index("### Phase 1:") : analyst.index("### Phase 2:")]

    assert "pass_with_exceptions" not in analyst
    assert "status in {" not in phase1
    assert "resolve_effective_report_state" not in phase1
    assert "`ARTIFACT_CHAIN` is not validated here" in phase1
    assert "schema_version=1" in phase1 and "repository_plan_invalid" in phase1
    item4 = analyst[analyst.index("4. Every exact path in `ARTIFACT_CHAIN.commit_whitelist_artifacts`") :]
    item4 = item4[: item4.index("5. Post-chain artifacts")]
    assert "dev-report-<TASK_ID>.effective.json" in item4 and "admitted into this list too" in item4


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

    # P3 R4 / P4 R3: close QA closes only on Step 0's chain_pass, the one
    # closeable disposition (its CHAIN line carries data fields, no status),
    # and consumes no disclosed-exceptions field.
    assert "`Disposition: chain_pass`" in section
    assert "the resolver's one closeable" in flat
    assert "status in {" not in section
    assert "disclosed_exceptions" not in section
    assert "_exceptions" not in text


def test_spec_update_consumes_lane_matrix_without_fake_parent_context() -> None:
    text = _read("commands/spec-update.md")
    section = text[
        text.index("## Continuation-spec mode") :
        text.index("## Temp-note mode")
    ]
    flat = _squash(section)

    assert FIXED_ENTRYPOINT_RUN in section
    assert "`artifact_paths`, `report_paths`, `qa_inputs`, and" in section
    assert "`lanes[]`" in section
    assert "every lane ticket/context/dev/QA" in flat
    assert "must not create, a parent context" in flat
    assert "fabricate missing parent artifacts" in flat
