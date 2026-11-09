"""P5-31: `Skill(codex:*)` stays out of settings.json's permissions, and lesson 15 keys on the human-only marker.

P5's plan (R5, A15) and P9's A13 asked for a `Skill(codex:*)` deny. P5 decided against it, by evidence that holds on
d64fa96: /codex is not a human-only command. commands/codex.md carries no `disable-model-invocation: true`; the
codex consultation include and /do call it through the Skill tool under `--codex` (and /close's QA, /commit's dev);
posttool-codex-skill-ledger.py (PostToolUse, matcher Skill) writes the ledger entry that subagentstop-codex-enforce.py
requires at a bound subagent's stop. A denied Skill call never runs, so its PostToolUse never fires: with the deny,
every `--codex` run's bound stops are refused with no action that clears them (D25). CLAUDE.md lesson 15 asks a deny
for each human-only command; this file pins that rule by the marker itself, so a rename of the one Skill call in
commands/do.md (which test_skill_deny_coverage.py reads) cannot turn codex into a "missing deny".
"""
from __future__ import annotations

import glob
import json
import os
import re

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTROL = {"allow", "restart", "checkpoint", "tickets"}
_MARKER = re.compile(r"^disable-model-invocation:\s*true\s*$", re.M)
_CODEX_CALL = re.compile(r"""Skill\((?:skill=)?["']?codex["']?[,)]""")


def _settings() -> dict:
    with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _frontmatter(stem: str) -> str:
    with open(os.path.join(ROOT, "commands", stem + ".md"), encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith("---\n"), stem
    return text[4:text.index("\n---", 4)]


def _stems() -> set:
    return {n[:-3] for n in os.listdir(os.path.join(ROOT, "commands"))
            if n.endswith(".md") and n[:-3] not in ("INDEX", "README")}


def _registered(event: str, script: str, matcher: str) -> bool:
    for block in _settings().get("hooks", {}).get(event, []):
        if block.get("matcher") == matcher and any(script in h.get("command", "") for h in block.get("hooks", [])):
            return True
    return False


def test_codex_is_not_marked_human_only():
    assert not _MARKER.search(_frontmatter("codex"))


def test_the_pipeline_texts_call_codex_through_the_skill_tool():
    paths = []
    for pattern in ("agents/*.md", "commands/*.md", "templates/prompt-includes/*.md", "skills/**/*.md"):
        paths += glob.glob(os.path.join(ROOT, pattern), recursive=True)
    callers = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            if _CODEX_CALL.search(fh.read()):
                callers.append(os.path.relpath(path, ROOT))
    assert "templates/prompt-includes/codex-consultation.md" in callers, callers


def test_the_codex_ledger_is_written_only_by_the_skill_calls_posttooluse():
    assert _registered("PostToolUse", "hooks/posttool-codex-skill-ledger.py", "Skill")
    assert _registered("SubagentStop", "hooks/subagentstop-codex-enforce.py", "*")


def test_no_permission_rule_names_the_codex_skill():
    perms = _settings()["permissions"]
    hits = {k: [r for r in perms.get(k, []) if r.startswith("Skill(codex")] for k in ("deny", "ask")}
    assert hits == {"deny": [], "ask": []}, hits


def test_every_human_only_command_has_its_skill_deny_and_no_other_command_has_one():
    deny = set(_settings()["permissions"]["deny"])
    marked = {s for s in _stems() if _MARKER.search(_frontmatter(s))}
    missing = sorted(s for s in marked - CONTROL if f"Skill({s}:*)" not in deny)
    assert not missing, "human-only commands without a Skill deny (CLAUDE.md lesson 15): " + ", ".join(missing)
    unmarked_denied = sorted(s for s in _stems() - marked if f"Skill({s}:*)" in deny)
    assert not unmarked_denied, "model-invocable commands denied to the Skill tool: " + ", ".join(unmarked_denied)
