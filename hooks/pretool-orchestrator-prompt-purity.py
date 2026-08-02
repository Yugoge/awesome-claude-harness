#!/usr/bin/env python3
"""
PreToolUse hook: Orchestrator Prompt Purity.

Intercepts Agent tool dispatches from the main-agent (orchestrator) to
subagents and rejects dispatch prompts that prescribe HOW (tool names,
shell-command fragments, shell syntax, fenced bash blocks). Orchestrator
prompts must describe WHAT (problem, constraints, acceptance criteria)
only; subagents choose their own toolchain per their agent.md.

Behavior contract (BA spec ba-spec-redev-prompt-purity-20260426.md
section "Hook Behavior Contract"):
  - Read PreToolUse Agent payload JSON from stdin.
  - Inspect tool_input.prompt.
  - Match four blacklist categories:
      1. Tool-name prescription (use|via|invoke|call|run + ToolName + tool)
      2. Shell-command tokens with option syntax (sed/jq/curl/git/...)
      3. Shell-syntax tokens ($(...) heredoc redirection chain pipe)
      4. Fenced bash blocks (```bash / ```sh / ```shell / ```zsh)
  - Plus one overnight-gated category: <options> XML blocks.
  - On hit: emit a warning to stderr (warn-only — never blocks).
  - On miss: exit 0 silently.
  - Always exit 0 (this hook never hard-blocks).
  - Fail-open on parse errors / missing fields / unexpected exceptions
    so a malformed payload never blocks legitimate work.

Exemptions:
  - Subagent dispatches (data.agent_id is truthy) bypass the scan
    entirely; this hook governs orchestrator -> subagent dispatch only.
  - Content delimited by <USER_VERBATIM>...</USER_VERBATIM> markers is
    redacted before scanning so user-quoted text containing tool names
    does not trigger false positives.
  - Standard dev-registry sentinel-registration boilerplate
    ("cat > .../.claude/dev-registry/<sid>/<role>.json << 'REGEOF'") is
    stripped before scanning because it is subagent-internal scaffolding,
    not orchestrator HOW-prescription.

Exit codes:
  0  Always (this hook is warn-only; never blocks).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


# Rule-doc pointers are derived from THIS hook's own on-disk location
# (<harness-home>/hooks/<name>.py), so the stderr message names the files that
# actually exist for the invoking user instead of an author-absolute literal.
_HARNESS_HOME = Path(__file__).resolve().parent.parent

RULE_DOC_POINTER = (
    f'See {_HARNESS_HOME / "commands" / "dev.md"} "Orchestrator Prompt Purity" section'
    f' and {_HARNESS_HOME / "CLAUDE.md"} "Orchestrator Prompt Purity" section.'
)

STDERR_HEADER = (
    "⚠ prompt-purity warning: HOW prescription detected (not blocking). Prefer describing WHAT only."
)

# PRESCRIBED_TOOL_NAMES: built-in tool names that the orchestrator must not
# prescribe imperatively in subagent dispatch prompts. The bare token "Skill"
# is intentionally OMITTED (T1.1 bugfix harness-bugfix-20260427): "Skill" is
# the meta-delegation primitive — it appears legitimately in narrative prose
# (e.g. "the Skill tool exists for delegating to other models") and in the
# orchestrator's own dev.md instructions for codex consultation. False-firing
# on bare "Skill" caused valid dispatches to be blocked. The other built-in
# tool names below remain enforced because prescribing them substitutes a
# specific HOW for the desired WHAT.
PRESCRIBED_TOOL_NAMES = (
    r"Write|Edit|Read|Bash|Glob|Grep|Agent|TodoWrite|"
    r"WebFetch|WebSearch|NotebookEdit|EnterWorktree|ExitWorktree|"
    r"AskUserQuestion|ScheduleWakeup|CronCreate|CronDelete|CronList|"
    r"TaskStop|mcp__\w+"
)

TOOL_PRESCRIPTION_PATTERNS = (
    re.compile(
        r"\b(?:Use|use|using|Using|via|Via|invoke|Invoke|call|Call|run|Run)\b"
        r"\s+(?:the\s+)?"
        r"(?:" + PRESCRIBED_TOOL_NAMES + r")\b"
        r"\s+tool\b",
    ),
    re.compile(
        r"\b(?:" + PRESCRIBED_TOOL_NAMES + r")\b\s+tool\b\s+(?:to|for)\b",
    ),
    re.compile(
        r"\(\s*not\s+(?:" + PRESCRIBED_TOOL_NAMES + r")\b",
    ),
)

SHELL_COMMANDS = (
    r"sed|awk|curl|wget|jq|yq|python3|node|npm|pip|"
    r"mkdir|chmod|chown|cp|mv|rm|ln|tar|gzip|gunzip|find|xargs|"
    r"kill|pkill|systemctl|docker|kubectl|ssh|scp|rsync"
)
SHELL_COMMAND_PATTERNS = (
    re.compile(
        r"\b(?:" + SHELL_COMMANDS + r")\b"
        r"\s+(?:-{1,2}[A-Za-z][\w-]*|<<\s*['\"]?\w+['\"]?|>>?\s*\S|2>&?\d?|\|)",
    ),
    re.compile(
        r"\bgit\s+(?:checkout|reset|revert|push|merge|rebase|cherry-pick|"
        r"stash|branch|commit|add|rm|mv|clone|fetch|pull)\b\s+\S",
    ),
)

SHELL_SYNTAX_PATTERNS = (
    re.compile(r"\$\([^)]+\)"),
    re.compile(r"<<\s*['\"]?[A-Za-z_]\w*['\"]?"),
    re.compile(r"&&\s*\S"),
    re.compile(r"\|\|\s*\S"),
    re.compile(
        r"\|\s+(?:" + SHELL_COMMANDS + r"|grep|cat|head|tail|sort|uniq|wc|tr|cut)\b",
    ),
    re.compile(r"\S\s*>{1,2}\s*[\w./~-]+"),
    re.compile(r"\S\s*2>&\d"),
)

FENCED_BASH_PATTERN = re.compile(
    r"```(?:bash|sh|shell|zsh)\b",
    re.IGNORECASE,
)
FENCED_UNTAGGED_BASH_PATTERN = re.compile(
    r"```\s*\n\s*(?:\$\s|cd\s|export\s|source\s|alias\s|cat\s|ls\s|echo\s)",
)

# Overnight-gated category: orchestrator MUST NOT dispatch <options> XML
# blocks during an active /dev-overnight session. The block prompt would
# cause the chat UI to go idle awaiting user input even though the Stop
# hook is blocking termination -- the documented Stop-continuation contract
# is overridden in practice by interrogative agent output. See BA spec
# ba-spec-stop-hook-gap-20260426-2250.md (M2 / AC2).
OPTIONS_XML_PATTERNS = (
    re.compile(r"<options>", re.IGNORECASE),
    re.compile(r"<option\s", re.IGNORECASE),
)
OPTIONS_XML_HEADER = (
    "orchestrator must not dispatch <options> blocks during overnight; "
    "choose autonomously or write a deadlock report and skip."
)
OPTIONS_XML_LABEL = "options-xml block (overnight forbids)"

USER_VERBATIM_RE = re.compile(
    r"<USER_VERBATIM>.*?</USER_VERBATIM>",
    re.DOTALL,
)
DEV_REGISTRY_HEREDOC_RE = re.compile(
    r"cat\s*>\s*/root/\.claude/dev-registry/[^\n]*<<\s*['\"]?REGEOF['\"]?"
    r".*?\nREGEOF\b",
    re.DOTALL,
)
# Pre-redact <options>...</options> XML blocks before the generic 4-category
# scan so XML closing-tag tokens (e.g. `</options>`, `n>A`) cannot collide
# with SHELL_SYNTAX_PATTERNS' redirection regex. The OPTIONS_XML category
# scans the UN-redacted prompt separately (overnight-gated) so it can still
# fire its dedicated header when active.
OPTIONS_XML_BLOCK_RE = re.compile(
    r"<options\b[^>]*>.*?</options\s*>",
    re.IGNORECASE | re.DOTALL,
)

# T1.1 bugfix (harness-bugfix-20260427): angle-bracket documentation
# placeholders like <SPEC_ID>, <agent-name>, <cp-NN>, <role>, <N> are a
# documentation convention denoting variable names — they are NOT shell
# syntax, NOT tool prescriptions, and NOT prescriptive HOW. Redact them
# before the 4-category scan so they cannot accidentally match any pattern
# (e.g. `<x>` could collide with redirection-style heuristics). The match
# is restricted to simple identifier-shape contents (letters, digits,
# underscore, hyphen) with no whitespace or attribute syntax, so it does
# NOT match real XML elements with attributes (e.g. `<option name="a">`).
# The OPTIONS_XML category scans the UN-redacted prompt separately, so this
# redaction never weakens the overnight OPTIONS_XML enforcement (AC5).
PLACEHOLDER_TOKEN_RE = re.compile(r"<[A-Za-z][A-Za-z0-9_-]*>")


def _redact_exempt_regions(prompt: str) -> str:
    redacted = USER_VERBATIM_RE.sub(" [USER_VERBATIM_REDACTED] ", prompt)
    redacted = DEV_REGISTRY_HEREDOC_RE.sub(
        " [DEV_REGISTRY_REGISTRATION_REDACTED] ", redacted,
    )
    redacted = OPTIONS_XML_BLOCK_RE.sub(
        " [OPTIONS_XML_BLOCK_REDACTED] ", redacted,
    )
    redacted = PLACEHOLDER_TOKEN_RE.sub(
        " [PLACEHOLDER_REDACTED] ", redacted,
    )
    return redacted


def _state_file_has_future_end_time(state_path: Path, now: datetime) -> bool:
    try:
        data = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    end_time_str = data.get("end_time")
    if not end_time_str:
        return False
    try:
        end_time = datetime.fromisoformat(end_time_str)
    except (TypeError, ValueError):
        return False
    if end_time.tzinfo is not None:
        end_time = end_time.replace(tzinfo=None)
    return end_time > now


def _overnight_active() -> bool:
    """Return True iff any .claude/overnight-state-*.json exists with a
    non-expired end_time. Fail-soft on any error.
    """
    try:
        project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
        claude_dir = project_dir / ".claude"
        if not claude_dir.is_dir():
            return False
        now = datetime.now()
        return any(
            _state_file_has_future_end_time(p, now)
            for p in claude_dir.glob("overnight-state-*.json")
        )
    except Exception:
        return False


def _truncate_snippet(text: str, limit: int = 80) -> str:
    cleaned = text.replace("\n", " ").replace("\r", " ")
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned


def _scan_category(prompt: str, patterns, category_label: str):
    for pat in patterns:
        m = pat.search(prompt)
        if m:
            return (category_label, _truncate_snippet(m.group(0)))
    return None


def _scan_fenced_blocks(prompt: str):
    m = FENCED_BASH_PATTERN.search(prompt)
    if m:
        return ("fenced bash block (tagged)", _truncate_snippet(m.group(0)))
    m = FENCED_UNTAGGED_BASH_PATTERN.search(prompt)
    if m:
        return (
            "fenced bash block (untagged shell content)",
            _truncate_snippet(m.group(0)),
        )
    return None


def _scan_generic_categories(redacted: str):
    categories = [
        (TOOL_PRESCRIPTION_PATTERNS, "tool-name prescription"),
        (SHELL_COMMAND_PATTERNS, "shell-command token"),
        (SHELL_SYNTAX_PATTERNS, "shell-syntax token"),
    ]
    for patterns, label in categories:
        hit = _scan_category(redacted, patterns, label)
        if hit:
            return hit
    return _scan_fenced_blocks(redacted)


def _scan_prompt(prompt: str):
    # OPTIONS_XML scans the un-redacted prompt FIRST when overnight is active.
    if _overnight_active():
        hit = _scan_category(prompt, OPTIONS_XML_PATTERNS, OPTIONS_XML_LABEL)
        if hit:
            return hit
    redacted = _redact_exempt_regions(prompt)
    return _scan_generic_categories(redacted)


_OPTIONS_XML_REMEDY = (
    "describe the work autonomously: pick one path,\n"
    "            execute it, or write docs/dev/overnight-deadlock-<ts>.md\n"
    "            and skip to the next pipeline. Defer all user-input\n"
    "            questions to the end-of-overnight summary."
)
_GENERIC_REMEDY = (
    "describe the desired end-state (problem, constraints,\n"
    "            acceptance criteria) and let the subagent select its\n"
    "            own tool per its agent.md."
)


def _header_remedy_for(category: str):
    if category == OPTIONS_XML_LABEL:
        return OPTIONS_XML_HEADER, _OPTIONS_XML_REMEDY
    return STDERR_HEADER, _GENERIC_REMEDY


def _emit_block(category: str, snippet: str) -> None:
    header, remedy = _header_remedy_for(category)
    msg = (
        f"{header}\n"
        f"  category: {category}\n"
        f'  snippet:  "{snippet}"\n'
        f"  rule:     {RULE_DOC_POINTER}\n"
        f"  remedy:   {remedy}\n"
    )
    sys.stderr.write(msg)
    sys.stderr.flush()


def _parse_payload():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None


def _extract_prompt(data: dict):
    tool_name = data.get("tool_name") or data.get("toolName") or ""
    if tool_name and tool_name != "Agent":
        return None
    tool_input = data.get("tool_input") or data.get("toolInput") or {}
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return None
    return prompt


def _route_hit(category: str, snippet: str, is_subagent: bool) -> int:
    """Route a scan hit. User policy: prompt-purity is WARNING-ONLY, never
    blocking. All categories emit to stderr but exit 0. Subagent dispatches
    are exempt entirely.
    """
    if is_subagent:
        return 0
    _emit_block(category, snippet)
    return 0


def main() -> int:
    data = _parse_payload()
    if data is None:
        return 0
    prompt = _extract_prompt(data)
    if prompt is None:
        return 0
    hit = _scan_prompt(prompt)
    if hit is None:
        return 0
    category, snippet = hit
    is_subagent = bool(data.get("agent_id"))
    return _route_hit(category, snippet, is_subagent)


if __name__ == "__main__":
    sys.exit(main())
