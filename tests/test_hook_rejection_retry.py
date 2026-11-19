"""A hook-rejected operation is reported, never asked about, and never retried: only the owner's own /allow grant, typed by him, lets it through (dev, paseo-daemon, clean); an operation no grant can let through is withdrawn, never left to the owner's own run."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands"
NO_RETRY = re.compile(r"retr(?:y|ies), disguises? or circumvents?")
RETRY_ON_ANSWER = re.compile(r"[Ww]ith the answer \(or after|until it is answered|answer (?:authorizes|releases) (?!no)")
OWNER_RUN = re.compile(r"himself|herself|themselves|\bhis\b|\bhe\b|own run\b|outside (?:the|this) session|by hand|"
                       r"in a terminal|on (?:his|her|their) (?:own )?machine")


def _dev_rule() -> str:
    text = (COMMANDS / "dev.md").read_text(encoding="utf-8")
    match = re.search(r"^\*\*Hook rejection \(a process step, never a terminal\):\*\*.*$", text, re.M)
    assert match, "commands/dev.md has no hook-rejection paragraph"
    return match.group(0)


def _paseo_rule() -> str:
    text = (COMMANDS / "paseo-daemon.md").read_text(encoding="utf-8")
    match = re.search(r"^- DO NOT bypass, wrap, or edit hooks.*?(?=^- |^#|\Z)", text, re.M | re.S)
    assert match, "commands/paseo-daemon.md has no hook-rejection bullet"
    return " ".join(match.group(0).split())


def _clean_rule() -> str:
    text = (COMMANDS / "clean.md").read_text(encoding="utf-8")
    match = re.search(r"^\*\*Hook rejection \(a process step, never a terminal\):\*\*.*$", text, re.M)
    assert match, "commands/clean.md has no hook-rejection paragraph"
    return match.group(0)


def test_dev_and_paseo_retry_a_rejected_operation_only_after_the_owners_allow() -> None:
    for name, rule in (("dev.md", _dev_rule()), ("paseo-daemon.md", _paseo_rule())):
        assert NO_RETRY.search(rule), name
        assert "AskUserQuestion" not in rule and "the pause" not in rule, name
        assert "`/allow` grant for it, typed as the owner's own prompt when the owner chooses" in rule and "no agent asks for one" in rule, name
        assert OWNER_RUN.findall(rule) == [], name
        assert "#4" in rule and "acceptance criterion stays achievable without it" in rule, name
        assert "reported as not met" in rule, name
        assert re.search(r"refusal never ends the (?:cycle|command)", rule), name
        assert RETRY_ON_ANSWER.findall(rule) == [], name
    dev = _dev_rule()
    assert "(`hooks/pretool-tool-policy.py`) is not run again in this session: it is withdrawn" in dev
    assert "nobody asks the owner about it" in dev
    paseo = _paseo_rule()
    assert "a hook that reads no grant goes on refusing it: the operation is withdrawn" in paseo
    assert "Nobody asks the owner about a hook rejection" in paseo


def test_dev_names_both_kinds_of_refusing_hook_and_the_orchestrator_too() -> None:
    rule = _dev_rule()
    assert rule.count("neither the orchestrator nor any subagent") == 1
    assert "a producer question asks only what the owner wants, never about a refusal" in rule
    for hook in ("hooks/pretool-git-privilege-guard.py", "hooks/pretool-block-branch-pr-worktree.py",
                 "hooks/pretool-tool-policy.py"):
        assert (ROOT / hook).is_file() and f"`{hook}`" in rule, hook


def test_clean_names_every_refusal_and_withdraws_what_the_tool_policy_refused() -> None:
    rule = _clean_rule()
    assert (ROOT / "hooks/pretool-tool-policy.py").is_file()
    assert "Nobody asks the owner about it" in rule and "AskUserQuestion" not in rule
    assert re.search(r"`hooks/pretool-tool-policy\.py` refused is not run again in this session \([^)]*\); "
                     r"the report names it as a follow-up for a /dev cycle", rule)
    assert "a /dev cycle's dev role, whose row in `policies/tool-policy.v1.json` allows `*`, may write the path" in rule
    policy = json.loads((ROOT / "policies/tool-policy.v1.json").read_text(encoding="utf-8"))
    assert "*" in policy["roles"]["dev"]["allowed_write_path_prefixes"]
    assert "the owner's own `/allow` grant for it (for example `/allow git commit`), typed as the owner's own prompt" in rule
    assert ("recorded, with its exact operation, the hook's output and, where the refusing hook reads `/allow` "
            "grants, the exact `/allow` line the owner could type, as that action's outcome in Steps 17 and 18") in rule
    assert OWNER_RUN.findall(rule) == []


def test_the_three_hook_rejection_rules_agree_on_the_report_and_the_grant() -> None:
    for name, rule in (("dev.md", _dev_rule()), ("paseo-daemon.md", _paseo_rule()), ("clean.md", _clean_rule())):
        assert NO_RETRY.search(rule), name
        assert "AskUserQuestion" not in rule and "releases no gate" not in rule, name
        assert "`/allow`" in rule and "withdrawn" in rule and "typed as the owner's own prompt when the owner chooses" in rule, name
        assert OWNER_RUN.findall(rule) == [], name
        assert RETRY_ON_ANSWER.findall(rule) == [], name
