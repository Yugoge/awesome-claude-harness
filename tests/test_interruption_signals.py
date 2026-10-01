"""Coverage for tiered interruption detection and the recall it restores.

Every banner asserted here was measured in the real transcript corpus under
``/var/lib/claude-accounts/*/claude/projects`` on 2026-09-30. The ``FUTURE_*``
cases are deliberately invented: they exist to prove the grammar generalises over
the scope word rather than enumerating it, which is the defect that made a whole
``/dev`` fan-out discover zero recoverable candidates.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import interruption_signals as sig  # noqa: E402
from lib import subagent_restart as restart  # noqa: E402


# --------------------------------------------------------------- measured banners

# The harness wrapper the parent records around a killed child.
WRAPPER = "Agent terminated early due to an API error: {} (error type rate_limit, HTTP 429, request id req_011X, model sent to the API: claude-fable-5)"

MEASURED_QUOTA = [
    # The exact text that returned zero candidates and prompted this fix.
    pytest.param(WRAPPER.format("You've hit your weekly limit · resets 2pm (UTC)"), id="weekly-wrapped"),
    pytest.param("You've hit your weekly limit · resets 2pm (UTC)", id="weekly-bare"),
    pytest.param("You've hit your session limit · resets 4:50am (UTC)", id="session-bare"),
    pytest.param("You’ve hit your session limit · resets 9:50am (UTC)", id="unicode-apostrophe"),
    pytest.param("You've hit your session limit - resets 12pm (UTC)", id="hyphen-separator"),
    pytest.param("You've hit your session limit; resets in 2h", id="duration-reset"),
    pytest.param(
        "You've reached your Fable 5 limit. Switch to another model, or manage "
        "usage credits at claude.ai/settings/usage?from=cc_cli_limit_message, to continue.",
        id="model-scoped-limit",
    ),
    # The old punctuation-only gap could not step over the word "type".
    pytest.param("(error type rate_limit, HTTP 429)", id="error-type-gap"),
]

MEASURED_INTERRUPT = [
    pytest.param("Agent terminated early due to an API error: API Error: 529 Overloaded.", id="overloaded-529"),
    pytest.param(
        "Agent terminated early due to an API error: API Error: Response stalled "
        "mid-stream. The response above may be incomplete.",
        id="stalled-midstream",
    ),
    pytest.param("The agent did NOT finish its task — treat these results as incomplete.", id="did-not-finish"),
    pytest.param("Request interrupted by user", id="user-abort"),
]

# Invented scope words. A phrase list fails these by construction; a grammar
# that treats the scope word as a gap does not.
FUTURE_QUOTA = [
    pytest.param("You've hit your monthly limit · resets tomorrow (UTC)", id="future-monthly"),
    pytest.param("You've hit your 5-hour limit · resets 3:15pm", id="future-5-hour"),
    pytest.param("You've exhausted your Opus 6 allowance.", id="future-opus-6"),
    pytest.param("Your account has exceeded its enterprise seat quota.", id="future-seat-quota"),
]

NON_SIGNALS = [
    pytest.param("Implementation complete. All 21 tests pass.", id="plain-success"),
    pytest.param("The script resets the counter to 0 on each run.", id="resets-counter"),
    pytest.param("We should add a token bucket to smooth request bursts.", id="rate-prose"),
    pytest.param("", id="empty"),
]


@pytest.mark.parametrize("text", MEASURED_QUOTA + FUTURE_QUOTA)
def test_quota_banners_are_detected(text: str) -> None:
    signal = sig.classify_text(text)
    assert signal is not None, "quota banner went undetected"
    assert signal.kind == sig.KIND_QUOTA
    assert sig.is_quota_text(text)
    # A quota kill is also an interruption; callers asking the broader question
    # must not get False merely because the more specific label won.
    assert sig.is_interrupt_text(text)


@pytest.mark.parametrize("text", MEASURED_INTERRUPT)
def test_interruption_banners_are_detected(text: str) -> None:
    signal = sig.classify_text(text)
    assert signal is not None, "interruption banner went undetected"
    assert sig.is_interrupt_text(text)


@pytest.mark.parametrize("text", NON_SIGNALS)
def test_ordinary_prose_raises_no_signal(text: str) -> None:
    assert sig.classify_text(text) is None
    assert not sig.is_quota_text(text)
    assert not sig.is_interrupt_text(text)


def test_harness_wrapper_outranks_bare_banner() -> None:
    """The machine token in the wrapper must win over the human banner tier."""
    wrapped = sig.classify_text(WRAPPER.format("You've hit your weekly limit"))
    bare = sig.classify_text("You've hit your weekly limit · resets 2pm (UTC)")
    assert wrapped is not None and bare is not None
    assert wrapped.tier == sig.TIER_HARNESS
    assert bare.tier == sig.TIER_BANNER
    assert wrapped.rank > bare.rank


def test_min_tier_filters_weak_evidence() -> None:
    bare = "You've hit your weekly limit · resets 2pm (UTC)"
    assert sig.is_quota_text(bare, min_tier=sig.TIER_BANNER)
    assert not sig.is_quota_text(bare, min_tier=sig.TIER_STRUCTURAL)


def test_weak_quota_hit_does_not_suppress_a_stronger_interrupt_hit() -> None:
    """A quota hit below min_tier must not mask an interrupt hit above it.

    Here the quota evidence is banner-tier ("hit your weekly limit") while the
    interruption evidence is harness-tier ("terminated early"). Asking for
    harness-or-better must surface the interrupt signal, not report nothing.
    """
    text = "Agent terminated early due to an API error: You've hit your weekly limit"
    assert sig.classify_text(text).kind == sig.KIND_QUOTA  # banner tier allowed

    strong = sig.classify_text(text, min_tier=sig.TIER_HARNESS)
    assert strong is not None, "harness-tier interrupt evidence was suppressed"
    assert strong.kind == sig.KIND_INTERRUPTED
    assert strong.tier == sig.TIER_HARNESS
    assert sig.is_interrupt_text(text, min_tier=sig.TIER_HARNESS)


# --------------------------------------------------------------- structural tier


def test_structural_record_classifies_without_prose() -> None:
    signal = sig.classify_record({
        "type": "assistant",
        "isApiErrorMessage": True,
        "error": "rate_limit",
        "apiErrorStatus": 429,
    })
    assert signal is not None
    assert (signal.kind, signal.tier) == (sig.KIND_QUOTA, sig.TIER_STRUCTURAL)


def test_unknown_error_token_still_yields_recovery() -> None:
    """The anti-hardcode guarantee: a token nobody has seen is still an abort.

    ``isApiErrorMessage`` is written only when the harness killed the turn, so
    the verdict cannot depend on recognising the token. This is the property the
    enumerated phrase list lacked.
    """
    signal = sig.classify_record({
        "type": "assistant",
        "isApiErrorMessage": True,
        "error": "some_token_invented_in_2027",
    })
    assert signal is not None
    assert signal.kind == sig.KIND_INTERRUPTED
    assert signal.tier == sig.TIER_STRUCTURAL


@pytest.mark.parametrize("record", [
    {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn"}},
    {"isApiErrorMessage": False, "error": "rate_limit"},
    "not-a-dict",
    None,
])
def test_non_error_records_raise_no_structural_signal(record: object) -> None:
    assert sig.classify_record(record) is None


def test_strongest_prefers_structural_then_quota() -> None:
    banner = sig.Signal(sig.KIND_INTERRUPTED, sig.TIER_BANNER, "r1")
    structural = sig.Signal(sig.KIND_INTERRUPTED, sig.TIER_STRUCTURAL, "r2")
    quota = sig.Signal(sig.KIND_QUOTA, sig.TIER_STRUCTURAL, "r3")
    assert sig.strongest([None, banner, structural]) is structural
    assert sig.strongest([structural, quota]) is quota
    assert sig.strongest([None, None]) is None


# --------------------------------------------------------------- overlay


def test_overlay_extends_vocabulary_without_a_source_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = "Compute budget cap engaged for this tenant."
    assert sig.classify_text(novel) is None

    overlay = tmp_path / "signals.json"
    overlay.write_text(json.dumps({
        "quota_patterns": [r"\bbudget cap\b"],
        "quota_error_tokens": ["credit_exhausted"],
        "quota_http_status": [402],
    }), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_RESTART_SIGNAL_OVERLAY", str(overlay))

    signal = sig.classify_text(novel)
    assert signal is not None and signal.kind == sig.KIND_QUOTA
    token = sig.classify_record({"isApiErrorMessage": True, "error": "credit_exhausted"})
    assert token is not None and token.kind == sig.KIND_QUOTA
    status = sig.classify_record({"isApiErrorMessage": True, "error": "x", "apiErrorStatus": 402})
    assert status is not None and status.kind == sig.KIND_QUOTA


def test_malformed_overlay_never_disarms_the_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fat-fingered config must not take recovery down with it."""
    overlay = tmp_path / "broken.json"
    overlay.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_RESTART_SIGNAL_OVERLAY", str(overlay))
    assert sig.is_quota_text("You've hit your weekly limit · resets 2pm (UTC)")

    overlay.write_text(json.dumps({"quota_patterns": ["([unclosed"]}), encoding="utf-8")
    assert sig.is_quota_text("You've hit your weekly limit · resets 2pm (UTC)")

    monkeypatch.setenv("CLAUDE_RESTART_SIGNAL_OVERLAY", str(tmp_path / "absent.json"))
    assert sig.is_quota_text("You've hit your weekly limit · resets 2pm (UTC)")


# --------------------------------------------------------------- end-to-end discovery


def _record(role: str, content: list[dict]) -> dict:
    return {"type": role, "message": {"role": role, "content": content}}


def _agent_call(tool_id: str, description: str, *, background: bool = False) -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Agent",
        "input": {
            "description": description,
            "subagent_type": "ba",
            "prompt": f"Do exactly one issue: {description}",
            "run_in_background": background,
        },
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _child(transcript: Path, agent_id: str, tool_id: str, records: list[dict]) -> None:
    subagents = transcript.with_suffix("") / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / f"agent-{agent_id}.meta.json").write_text(
        json.dumps({"agentType": "ba", "description": "lane", "toolUseId": tool_id}),
        encoding="utf-8",
    )
    _write_jsonl(subagents / f"agent-{agent_id}.jsonl", records)


def test_weekly_limit_lane_is_discovered(tmp_path: Path) -> None:
    """Regression for the reported zero-candidate result.

    A lane killed by the weekly-limit banner must be discovered. Under the
    enumerated phrase list its evidence list came back empty and it was dropped
    at ``if not evidence: continue``.
    """
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tool_id = "toolu_l2"
    _write_jsonl(transcript, [
        _record("assistant", [_agent_call(tool_id, "L2 requirements")]),
        _record("user", [{
            "type": "tool_result",
            "tool_use_id": tool_id,
            "is_error": True,
            "content": [{"type": "text", "text": WRAPPER.format(
                "You've hit your weekly limit · resets 2pm (UTC)"
            ) + "\nagentId: agent-l2"}],
        }]),
    ])
    _child(transcript, "agent-l2", tool_id, [
        _record("assistant", [{"type": "text", "text": "partial analysis"}]),
    ])

    candidates = restart.discover_candidates(transcript)
    assert [item["agent_id"] for item in candidates] == ["agent-l2"]
    assert "quota_or_usage_limit" in candidates[0]["evidence"]


def test_background_lane_with_only_child_side_evidence_is_discovered(tmp_path: Path) -> None:
    """The fan-out case: parent holds no banner at all.

    A background child is launched, the launch result says only "Async agent
    launched successfully", and the API then kills the child. Nothing on the
    parent side carries interruption evidence, so text matching of ANY
    vocabulary finds nothing. The child's own machine-written record is the only
    evidence that exists, and recovery must use it.
    """
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tool_id = "toolu_bg"
    _write_jsonl(transcript, [
        _record("assistant", [_agent_call(tool_id, "L5 requirements", background=True)]),
        _record("user", [{
            "type": "tool_result",
            "tool_use_id": tool_id,
            "content": [{"type": "text", "text": "Async agent launched successfully.\nagentId: agent-l5"}],
        }]),
    ])
    _child(transcript, "agent-l5", tool_id, [
        _record("assistant", [{"type": "text", "text": "starting analysis"}]),
        {
            "type": "assistant",
            "isApiErrorMessage": True,
            "error": "rate_limit",
            "apiErrorStatus": 429,
            "message": {"role": "assistant", "model": "<synthetic>", "stop_reason": "stop_sequence"},
        },
    ])

    candidates = restart.discover_candidates(transcript)
    assert [item["agent_id"] for item in candidates] == ["agent-l5"]
    assert "quota_or_usage_limit_structural" in candidates[0]["evidence"]
    # interruption_line must stay on the PARENT axis: prepare_state compares it
    # against interruption_line_at_dispatch, so a child line number there would
    # corrupt the dispatch-progress test.
    parent_lines = sum(1 for _ in transcript.open(encoding="utf-8"))
    assert 1 <= candidates[0]["interruption_line"] <= parent_lines


def test_completed_child_is_still_never_resumed(tmp_path: Path) -> None:
    """Broadened recall must not resurrect the known false-positive class.

    A child that quotes a limit banner inside a finished end_turn report is
    reporting ON the outage, not a victim of it.
    """
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tool_id = "toolu_done"
    _write_jsonl(transcript, [
        _record("assistant", [_agent_call(tool_id, "report on the outage")]),
        _record("user", [{
            "type": "tool_result",
            "tool_use_id": tool_id,
            "content": [{"type": "text", "text":
                "Investigated: the banner was \"You've hit your weekly limit · "
                "resets 2pm (UTC)\".\nagentId: agent-done"}],
        }]),
    ])
    _child(transcript, "agent-done", tool_id, [
        {
            "type": "assistant",
            "message": {"role": "assistant", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "Report delivered."}]},
        },
    ])

    assert restart.discover_candidates(transcript) == []
