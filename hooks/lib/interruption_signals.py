#!/usr/bin/env python3
"""Tiered detection of subagent interruption / quota signals.

Decides whether a subagent was cut off — and whether a usage limit did it — from
three ranked evidence tiers, leading with the machine-written fields the harness
itself records rather than with banner prose.

WHY THIS MODULE EXISTS
----------------------
Recovery used to hinge on one enumerated phrase list (``QUOTA_RE`` in
``subagent_restart.py``), so every banner the author had not personally seen was
a silent zero-recovery event.  Measured against the real transcript corpus under
``/var/lib/claude-accounts/*/claude/projects`` on 2026-09-30, that list missed:

======================================================  ==============
banner (all harness-written, all real)                  old detector
======================================================  ==============
``You've hit your weekly limit · resets 2pm (UTC)``     MISS
``API Error: 529 Overloaded.``                          MISS
``API Error: Response stalled mid-stream.``             MISS
``The agent did NOT finish its task``                   MISS
``You've reached your Fable 5 limit.``                  accidental hit
======================================================  ==============

The ``Fable 5`` case is the tell: it matched only because the banner's
``claude.ai/settings/usage`` URL happened to fall inside a
``(?:anthropic|claude)[^\\n]{0,80}rate[-_ ]limit`` window.  Change the URL and
recovery breaks.  A detector whose hits are coincidences is not a detector.

The failure mode is structural, not a missing phrase: **the scope word is an
open set.**  ``session`` / ``weekly`` / ``Fable 5`` / ``5-hour`` / whatever ships
next quarter all slot into the same sentence frame, so enumerating them is
unwinnable by construction.  Adding "weekly" would only have bought time until
the next one.

THE THREE TIERS
---------------
``TIER_STRUCTURAL``
    Machine fields the harness writes, never prose.  A record carrying
    ``isApiErrorMessage: true`` means *the harness itself killed that turn on an
    API error*; that is dispositive regardless of wording, so an error token
    this module has never seen still yields recovery.  The token and
    ``apiErrorStatus`` only refine quota-vs-other.  This tier is the reason the
    open-vocabulary problem cannot recur here.

``TIER_HARNESS``
    The harness's own wrapper around a banner:
    ``Agent terminated early due to an API error: <banner> (error type
    rate_limit, HTTP 429, ...)``.  Machine-generated and stable, and it carries
    the machine token inline — so parse the *token*, not the human banner.

``TIER_BANNER``
    Last resort, when only human-facing text survives.  Expressed as a
    scope-agnostic **grammar** (sentence frames + co-occurrence), not a phrase
    list: ``you've <consume-verb> your <ANY SCOPE> limit`` matches every row of
    the table above and every scope word not yet invented.

Callers name the weakest tier they will accept, so broadening text recall never
silently weakens a caller that had structural proof available.

FALSE POSITIVES
---------------
Broadening recall cuts both ways: a child *reporting on* an outage quotes limit
banners verbatim, and 39 of 217 corpus candidates were exactly that
(``docs/reference/restart-detector-quota-text-match-false-positive-20260915.md``).
This module deliberately does not adjudicate that — it reports what a signal
looks like and how strong it is.  Suppressing self-reports stays with the
caller's structural gates (``_child_reported_end_turn``, ``RECOVERY_STATUS``),
which outrank every tier here.

EXTENDING WITHOUT A SOURCE PATCH
--------------------------------
Point ``CLAUDE_RESTART_SIGNAL_OVERLAY`` at a JSON file to add vocabulary at
runtime; entries are additive and never remove a default::

    {
      "quota_error_tokens": ["credit_exhausted"],
      "quota_http_status":  [402],
      "quota_patterns":     ["\\\\bbudget cap\\\\b"],
      "interrupt_patterns": ["\\\\bevicted\\\\b"]
    }

A malformed overlay (bad JSON, uncompilable regex) is ignored entry-by-entry and
never raises: a hook must not die because an operator fat-fingered a config.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, NamedTuple


# ---------------------------------------------------------------- tiers

TIER_STRUCTURAL = "structural"
TIER_HARNESS = "harness_wrapper"
TIER_BANNER = "banner_grammar"

#: Higher rank == stronger evidence.
TIER_RANK: dict[str, int] = {
    TIER_BANNER: 1,
    TIER_HARNESS: 2,
    TIER_STRUCTURAL: 3,
}

KIND_QUOTA = "quota"
KIND_INTERRUPTED = "interrupted"


class Signal(NamedTuple):
    """One detected interruption signal."""

    kind: str          # KIND_QUOTA | KIND_INTERRUPTED
    tier: str          # TIER_*
    rule: str          # stable id of the rule that fired, for debugging
    detail: str = ""   # short machine detail (token, status, matched span)

    @property
    def rank(self) -> int:
        return TIER_RANK.get(self.tier, 0)

    def accepts(self, min_tier: str) -> bool:
        return self.rank >= TIER_RANK.get(min_tier, 0)


# ---------------------------------------------------------------- normalisation

# Unicode variants the banners actually use; NFKC alone does not fold these.
_APOSTROPHES = "‘’ʼ′´`"
_SEPARATORS = "·•–—―− "


def normalize(text: str) -> str:
    """Casefold and fold away the punctuation variance banners drift across.

    ``You've hit your weekly limit · resets 2pm`` and its ``\\u2019``/``-``
    spellings must reduce to one string, otherwise the grammar below would need
    a variant per typographic accident — the very trap this module exists to
    avoid.
    """
    if not isinstance(text, str) or not text:
        return ""
    out = unicodedata.normalize("NFKC", text)
    out = out.translate({ord(ch): "'" for ch in _APOSTROPHES})
    out = out.translate({ord(ch): " " for ch in _SEPARATORS})
    return re.sub(r"\s+", " ", out.casefold())


# ---------------------------------------------------------------- grammar

# An open set by construction: session / weekly / monthly / "Fable 5" / 5-hour /
# whatever ships next.  Never enumerated -- only ever matched as a gap.
_NOUN = r"(?:limits?|quotas?|credits?|allowance)"
_CONSUME = r"(?:hit|hits|reached|reaches|exceed(?:ed|s)?|used up|ran out of|run out of|exhausted|out of)"
_SUBJECT = r"(?:you(?:'ve|'re| have)?|your account|this account|the account|we|this session)"
# Clock/duration shapes measured in the corpus: "2pm", "4:50am", "at 10am",
# "in 2h".  A bare digit is deliberately NOT enough ("resets the counter to 0").
_RESET_AT = (
    r"(?:\d{1,2}:\d{2}\s*(?:am|pm)?"
    r"|\d{1,2}\s*(?:am|pm)"
    r"|\d+\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes|d|day|days)\b"
    r"|noon|midnight|tomorrow|tonight)"
)

_QUOTA_GRAMMAR: tuple[tuple[str, str, str], ...] = (
    # Scope-agnostic sentence frame. The {0,60} gap is where session / weekly /
    # "Fable 5" / any future scope word lives, so none of them is named here.
    (
        "quota.consumed_possessive",
        TIER_BANNER,
        rf"\b{_SUBJECT}\b[^.\n]{{0,40}}?\b{_CONSUME}\b[^.\n]{{0,60}}?\b{_NOUN}\b",
    ),
    # Passive voice: "<scope> limit has been reached".
    (
        "quota.limit_reached_passive",
        TIER_BANNER,
        rf"\b{_NOUN}\b[^.\n]{{0,40}}?\b(?:has been |was |is )?(?:reached|exceeded|exhausted)\b",
    ),
    # Reset notice. The old pattern demanded an "at"/"in" preposition, which is
    # exactly why "resets 2pm (UTC)" was missed; the preposition is optional.
    ("quota.reset_notice", TIER_BANNER, rf"\bresets?\b\s*(?:at|in|on|by)?\s*{_RESET_AT}"),
    # Machine token inside the harness wrapper. The gap is WORD-tolerant (up to
    # three tokens), which is what "error type rate_limit" needs -- the old
    # punctuation-only class could not step over the word "type".
    (
        "quota.rate_limit_token",
        TIER_HARNESS,
        r"\b(?:error|err|code|status|type)\b(?:[\s\W]+\w+){0,3}[\s\W]*\brate[-_ ]?limits?\b",
    ),
    # Protocol-level facts, not prose: HTTP 429 is the rate-limit status.
    ("quota.http_429", TIER_HARNESS, r"\bhttp[\s:=/]*429\b|\b429 too many requests\b"),
    ("quota.rate_limit_bare", TIER_BANNER, r"\brate[-_]limits?\b"),
    # Model-scoped limit banners route the operator to the usage/credits page.
    (
        "quota.usage_upsell",
        TIER_BANNER,
        r"\bmanage usage credits\b|\bswitch to another model\b|\bupgrade (?:your )?plan\b",
    ),
)

_INTERRUPT_GRAMMAR: tuple[tuple[str, str, str], ...] = (
    (
        "interrupt.user_abort",
        TIER_BANNER,
        r"\b(?:request interrupted|interrupted by user|aborterror|aborted|cancell?ed)\b",
    ),
    # Harness-written wrapper: "Agent terminated early due to an API error: ..."
    ("interrupt.terminated_early", TIER_HARNESS, r"\bterminated early\b"),
    # Harness-written tail on a truncated Agent result.
    (
        "interrupt.not_finished",
        TIER_HARNESS,
        r"\bdid not finish\b|\bnever finished\b",
    ),
    (
        "interrupt.partial_output",
        TIER_HARNESS,
        r"\bpartial output recovered\b|\bmay be incomplete\b|\bcut off\b|\btruncated\b",
    ),
    ("interrupt.stalled", TIER_HARNESS, r"\bstalled mid-?stream\b|\bresponse stalled\b"),
    ("interrupt.overloaded", TIER_BANNER, r"\boverloaded\b|\bhttp[\s:=/]*5\d\d\b"),
)


# ---------------------------------------------------------------- structural vocabulary

# Substring markers, matched against the harness's machine `error` token. These
# only ever REFINE quota-vs-other; an unrecognised token still yields
# KIND_INTERRUPTED via isApiErrorMessage, so a new token is never a silent drop.
_QUOTA_TOKEN_MARKERS: tuple[str, ...] = (
    "rate_limit", "ratelimit", "rate-limit", "quota", "usage_limit", "credit",
)
_QUOTA_HTTP_STATUS: frozenset[int] = frozenset({429})


# ---------------------------------------------------------------- overlay

_OVERLAY_CACHE: dict[str, Any] = {"key": None, "value": {}}


def _compile_list(raw: Any, rule_prefix: str, tier: str) -> list[tuple[str, str, re.Pattern[str]]]:
    out: list[tuple[str, str, re.Pattern[str]]] = []
    if not isinstance(raw, list):
        return out
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item:
            continue
        try:
            out.append((f"{rule_prefix}.overlay{index}", tier, re.compile(item, re.IGNORECASE)))
        except re.error:
            # One bad regex must not disarm the whole detector.
            continue
    return out


def overlay() -> dict[str, Any]:
    """Load (and mtime-cache) the operator overlay, or ``{}`` when unset."""
    path_raw = os.environ.get("CLAUDE_RESTART_SIGNAL_OVERLAY")
    if not path_raw:
        _OVERLAY_CACHE.update(key=None, value={})
        return {}
    path = Path(path_raw)
    try:
        key = f"{path}:{path.stat().st_mtime_ns}"
    except OSError:
        _OVERLAY_CACHE.update(key=None, value={})
        return {}
    if _OVERLAY_CACHE.get("key") == key:
        return _OVERLAY_CACHE["value"]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    _OVERLAY_CACHE.update(key=key, value=value)
    return value


CompiledRule = tuple[str, str, "re.Pattern[str]"]

# Compiled once at import: classify_text runs per tool_result across
# multi-hundred-MB transcripts, so the rule table must not be rebuilt per call.
_QUOTA_BASE: tuple[CompiledRule, ...] = tuple(
    (rid, tier, re.compile(pat, re.IGNORECASE)) for rid, tier, pat in _QUOTA_GRAMMAR
)
_INTERRUPT_BASE: tuple[CompiledRule, ...] = tuple(
    (rid, tier, re.compile(pat, re.IGNORECASE)) for rid, tier, pat in _INTERRUPT_GRAMMAR
)
#: Overlay rules, re-derived only when the overlay file's mtime key changes.
_RULE_CACHE: dict[str, Any] = {"key": None, KIND_QUOTA: (), KIND_INTERRUPTED: ()}


def _rules(kind: str) -> tuple[CompiledRule, ...]:
    base = _QUOTA_BASE if kind == KIND_QUOTA else _INTERRUPT_BASE
    data = overlay()
    if not data:
        return base
    key = _OVERLAY_CACHE.get("key")
    if _RULE_CACHE.get("key") != key:
        _RULE_CACHE.update({
            "key": key,
            KIND_QUOTA: tuple(_compile_list(data.get("quota_patterns"), "quota", TIER_BANNER)),
            KIND_INTERRUPTED: tuple(
                _compile_list(data.get("interrupt_patterns"), "interrupt", TIER_BANNER)
            ),
        })
    return base + _RULE_CACHE[kind]


def _quota_token_markers() -> tuple[str, ...]:
    extra = overlay().get("quota_error_tokens")
    if isinstance(extra, list):
        return _QUOTA_TOKEN_MARKERS + tuple(
            item.casefold() for item in extra if isinstance(item, str) and item
        )
    return _QUOTA_TOKEN_MARKERS


def _quota_http_status() -> frozenset[int]:
    extra = overlay().get("quota_http_status")
    if isinstance(extra, list):
        return _QUOTA_HTTP_STATUS | {item for item in extra if isinstance(item, int)}
    return _QUOTA_HTTP_STATUS


# ---------------------------------------------------------------- text tier


def classify_text(text: str, *, min_tier: str = TIER_BANNER) -> Signal | None:
    """Strongest text signal in ``text``, or ``None``.

    Quota is preferred over bare interruption whenever any quota rule fires: a
    quota kill IS an interruption, and the caller needs the more specific label
    to know whether waiting for a reset is what unblocks the resume.

    The two kinds are resolved INDEPENDENTLY before that preference applies.
    Collapsing them into one "strongest overall" pass would let a quota hit
    below ``min_tier`` suppress an interrupt hit above it — reporting no signal
    for text that plainly carries one.
    """
    body = normalize(text)
    if not body:
        return None

    def _best(kind: str) -> Signal | None:
        best: Signal | None = None
        for rule_id, tier, pattern in _rules(kind):
            match = pattern.search(body)
            if not match:
                continue
            signal = Signal(kind, tier, rule_id, match.group(0)[:80])
            if not signal.accepts(min_tier):
                continue
            if best is None or signal.rank > best.rank:
                best = signal
        return best

    return _best(KIND_QUOTA) or _best(KIND_INTERRUPTED)


def is_quota_text(text: str, *, min_tier: str = TIER_BANNER) -> bool:
    signal = classify_text(text, min_tier=min_tier)
    return signal is not None and signal.kind == KIND_QUOTA


def is_interrupt_text(text: str, *, min_tier: str = TIER_BANNER) -> bool:
    """True for any interruption signal, quota included.

    A quota kill is an interruption; a caller asking "was this cut off?" must not
    get False merely because the more specific quota label won.
    """
    return classify_text(text, min_tier=min_tier) is not None


# ---------------------------------------------------------------- structural tier


def classify_record(record: Any) -> Signal | None:
    """Classify one transcript record from its machine fields alone.

    ``isApiErrorMessage: true`` is written by the harness exactly when it aborted
    a turn on an API error, so its mere presence proves interruption — no prose
    is consulted and an unknown ``error`` token still recovers.  Measured record
    shape (1780 hits, corpus scan 2026-09-30)::

        {"type": "assistant", "isApiErrorMessage": true, "error": "rate_limit",
         "apiErrorStatus": 429, "message": {"stop_reason": "stop_sequence", ...}}
    """
    if not isinstance(record, dict):
        return None
    if record.get("isApiErrorMessage") is not True:
        return None
    token = record.get("error")
    token = token.strip().casefold() if isinstance(token, str) else ""
    status = record.get("apiErrorStatus")
    status = status if isinstance(status, int) and not isinstance(status, bool) else None

    if status in _quota_http_status():
        return Signal(KIND_QUOTA, TIER_STRUCTURAL, "quota.api_error_status", f"http={status}")
    if token and any(marker in token for marker in _quota_token_markers()):
        return Signal(KIND_QUOTA, TIER_STRUCTURAL, "quota.api_error_token", f"error={token}")
    # Unknown token: still a harness-aborted turn, so still recoverable work.
    return Signal(
        KIND_INTERRUPTED,
        TIER_STRUCTURAL,
        "interrupt.api_error_message",
        f"error={token or 'unspecified'}",
    )


def strongest(signals: Iterable[Signal | None]) -> Signal | None:
    """Highest-ranked signal, quota winning ties."""
    best: Signal | None = None
    for signal in signals:
        if signal is None:
            continue
        if best is None:
            best = signal
            continue
        if signal.rank > best.rank:
            best = signal
        elif signal.rank == best.rank and signal.kind == KIND_QUOTA and best.kind != KIND_QUOTA:
            best = signal
    return best
