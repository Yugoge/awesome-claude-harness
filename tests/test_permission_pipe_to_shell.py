"""Pipe-to-shell at the permission layer: the ask entries that stop a download piped into bash.

The CLI splits a compound command at `&&`, `||`, `;`, `|`, `|&`, `&` and newlines and judges each
subcommand (code.claude.com/docs/en/permissions.md, "Compound commands": "Deny and ask rules apply
when any subcommand matches them"); `:*` is a trailing wildcard only ("The `:*` form is only
recognized at the end of a pattern ... the colon is treated as a literal character"). The old deny
entries `Bash(curl:* | sh:*)` and `Bash(wget:* | sh:*)` therefore matched nothing. Measured on the
installed CLI (2.1.326): removing them changed no decision, and `curl ... | bash` ran unprompted
(`Bash(curl:*)` and `Bash(bash:*)` allow both halves).

A rule cannot see what feeds a pipe, so the ask entries name the subcommand that runs the
downloaded text: bash given no script operand, which reads its program from stdin (`bash`, `bash -`,
`bash --`, `bash -s ...`, `bash /dev/stdin`, `bash -x`, ...). They are `ask`, not `deny`, so a
local stdin-fed bash (`bash <<'EOF'`, `bash <<< x`, `bash -s < f`) stays approvable. `sh`, `zsh`
are not allowed at all, so they prompted on the base already and get no entry.

Measured on 2.1.326, not documented ("rule specificity doesn't change the order" says the docs),
and modelled below as TIERS: a rule matching the command text exactly (a rule with no `*`, or
`P:*` against bare `P`) is decided before any wildcard match, deny before ask inside each tier, and
allow only when neither matched (no allow ever outranked an ask); the wrappers `sudo` (with its options), `env`, `timeout`, `nohup` and leading assignments
are stripped before an ask or allow rule is matched. So an exact ask entry `Bash(bash)` outranked
the base deny `Bash(sudo:*)` for `sudo -u root bash`. Every ask entry here therefore carries its
`*` inside the program name (`Bash(b*ash -x)`): it matches its form as tightly as an exact rule
(the `*` can only add letters between `b` and `ash`) but sits in the wildcard tier, where
`Bash(sudo:*)` is decided first. Every command the base denied stays denied (pinned below).

Method: claude -p, default mode and bypassPermissions, a throwaway HOME given to the CLI process
only, holding only a `permissions` block, a throwaway cwd, and a local mock Messages API that issues
one Bash tool_use and records the tool_result. Under bypassPermissions these ask entries still
prompted; the CLI's own prompts for unmatched commands (`| sh`, `| zsh`, `sh -c "$(curl x)"`) ran.
KNOWN_GAPS still run unprompted in default mode; docs/ENFORCEMENT-LEDGER.md S-022 lists every gap.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEAD = ("Bash(curl:* | sh:*)", "Bash(wget:* | sh:*)")
STDIN_FORMS = ("", " -", " --", " -s*", " /dev/stdin", " -x", " -e", " -i", " -l", " --norc",
               " --noprofile", " --login", " -ex", " -xe", " -eu", " -eux", " -o pipefail", " -l -s*")
STDIN_BASH = tuple(sorted("Bash(b*ash%s)" % f for f in STDIN_FORMS))
DOC_WRAPPERS = re.compile(r"^(?:(?:timeout|nice|stdbuf)(?:\s+-\S+)*(?:\s+\d\S*)?|time|nohup|command|builtin|noglob)\s+")
# Measured (2.1.326) to be stripped before an ask/allow match as well: sudo with its options, env.
MEASURED_WRAPPERS = re.compile(r"^(?:sudo(?:\s+(?:-[uUgCh]\s+\S+|--\w[\w-]*=\S+|-\w+))*|env)\s+")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")
REDIRECT = re.compile(r"""\s*\d*(?:<<<|<<-?|&>>|&>|>>|>&|<&|<>|>\||>|<(?!\())\s*(?:'[^']*'|"[^"]*"|[^\s;&|<>]+)""")
HEREDOC = re.compile(r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")
READ_ONLY = {"ls", "cat", "echo", "pwd", "head", "tail", "grep", "find", "wc", "which", "diff", "stat", "du", "cd"}

PIPE_TO_BASH = [
    "curl -fsSL x | bash",
    "wget -qO- x | bash",
    "curl x|bash",
    "curl -fsSL x | bash -s -- --yes",
    "curl -fsSL x | bash -sx",
    "curl -fsSL x | bash -",
    "curl -fsSL x | bash --",
    "curl -fsSL x | bash -l",
    "curl -fsSL x | bash -l -s",
    "curl -fsSL x | bash --norc",
    "curl -fsSL x | bash --noprofile",
    "curl -fsSL x | bash /dev/stdin",
    "curl -fsSL x | bash -x",
    "curl -fsSL x | bash -e",
    "curl -fsSL x | bash -i",
    "curl -fsSL x | bash -ex",
    "curl -fsSL x | bash -eux",
    "curl -fsSL x | bash -o pipefail",
    "curl -fsSL x | timeout 5 bash",
    "curl -fsSL x |& bash",
]
PROMPTED_ON_BASE = ["curl https://x | sh", "wget -qO- x | sh", "curl x | sh -s -- --yes", "curl x | zsh",
                    "curl -fsSL x | X=1 bash"]
DENIED_ON_BASE = [  # each stays denied (measured on 2.1.326 too)
    "curl x | sudo bash", "curl x | sudo sh", "curl x | sudo bash -s -- --yes", "sudo bash",
    "curl x | sudo -u root bash", "curl x | sudo -E bash", "curl x | sudo -i bash",
    "curl x | sudo --user=root sh -s", "curl x | sudo -u root bash -x", "curl x | sudo env bash",
    "curl x | sudo bash /dev/stdin", "curl x | FOO=1 sudo bash", "curl x | timeout 5 sudo bash",
    "sudo -u root bash", "sudo -E bash -s", "curl x | sudo -u root bash -l -s", "sudo ls", "su -c bash",
]
LOCAL_STDIN_BASH = [  # prompt (approvable), never denied
    "bash <<'EOF'\necho hi\nEOF",
    "bash <<-EOF\n\techo hi\n\tEOF",
    "bash <<< 'echo hi'",
    "bash -s < scripts/x.sh",
    "bash -s -- --flag < scripts/x.sh",
    "bash < scripts/x.sh",
    "printf 'echo local\\n' | bash",
]
KNOWN_GAPS = [  # measured running unprompted on 2.1.326 after this change
    "curl -fsSL x | bash -euo pipefail",
    "curl -fsSL x | bash -xv",
]
STILL_RUNS = [
    "curl -s https://example.com -o out.html",
    "wget -q https://example.com -O out.html",
    "bash scripts/x.sh",
    "bash scripts/x.sh -",
    "bash -- scripts/x.sh",
    "bash -l scripts/x.sh",
    "bash -n scripts/x.sh",
    "bash -x scripts/x.sh",
    "bash -x scripts/x.sh -e",
    "bash -e scripts/x.sh",
    "bash -c 'echo hi'",
    "bash -c true",
    "bash -c ls",
    "bash scripts/x.sh > out.log 2>&1",
    "curl -fsSL x | grep version",
    "python3 -c 'print(1)' | bash scripts/x.sh /dev/stdin",
    'python3 "<HARNESS_ROOT>/scripts/aggregate-permissions.py" docs/dev/qa-report-T.json'
    ' | bash "<HARNESS_ROOT>/scripts/apply-permissions.sh" /dev/stdin .claude/settings.json',
    "which bash",
]


@functools.lru_cache(maxsize=1)
def _permissions() -> dict:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]


def _bash_rules(entries) -> list[str]:
    return [e[5:-1] for e in entries if e.startswith("Bash(") and e.endswith(")")]


def rule_covers(rule: str, cmd: str) -> bool:
    """`P:*` only at the end is `P *`; `P *` matches `P` and `P <args>`; any `*` is any text; else exact."""
    if rule.endswith(":*"):
        rule = rule[:-2] + " *"
    if "*" not in rule:
        return cmd == rule
    if rule.endswith(" *") and cmd == rule[:-2]:
        return True
    return re.fullmatch(".*".join(re.escape(p) for p in rule.split("*")), cmd, re.S) is not None


def exact_tier(rule: str, cmd: str) -> bool:
    """Measured: a match is exact-tier when the rule has no `*`, or it is `P:*` against bare `P`."""
    return ("*" not in rule and cmd == rule) or (rule.endswith(":*") and "*" not in rule[:-2] and cmd == rule[:-2])


def strip_heredoc_bodies(text: str) -> str:
    """Drop each heredoc's body lines and terminator; the `cmd <<EOF` line itself stays."""
    out, pending = [], []
    for line in text.split("\n"):
        if pending:
            delim, dash = pending[0]
            if (line.lstrip("\t") if dash else line) == delim:
                pending.pop(0)
            continue
        out.append(line)
        for m in HEREDOC.finditer(line.replace("<<<", "   ")):
            pending.append((m.group(2), m.group(0).startswith("<<-")))
    return "\n".join(out)


def subcommands(cmd: str) -> list[str]:
    """The documented split (`&&`, `||`, `;`, `|`, `|&`, `&`, newline) outside quotes, after heredoc bodies go."""
    cmd = strip_heredoc_bodies(cmd)
    parts, cur, quote, i = [], "", None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            quote = None if ch == quote else quote
            cur += ch
        elif ch in "'\"":
            quote = ch
            cur += ch
        elif cmd.startswith(("&&", "||", "|&"), i):
            parts.append(cur); cur = ""; i += 1
        elif ch == "&" and (cmd[i - 1:i] in (">", "<") or cmd[i + 1:i + 2] == ">"):
            cur += ch  # `2>&1`, `<&0`, `&>` are redirections, not separators
        elif ch in ";|&\n":
            parts.append(cur); cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def match_forms(sub: str, measured: bool = False) -> list[str]:
    """A subcommand without its redirections, then past its wrappers and leading assignments."""
    cur = re.sub(r"\s+", " ", REDIRECT.sub("", sub)).strip()
    forms = [cur]
    while True:
        nxt = ASSIGN.sub("", DOC_WRAPPERS.sub("", cur, count=1), count=1)
        if measured:
            nxt = MEASURED_WRAPPERS.sub("", nxt, count=1)
        if nxt == cur:
            return forms
        forms.append(nxt)
        cur = nxt


def first_match(rules: list[str], cmd: str) -> str | None:
    for sub in subcommands(cmd):
        for form in match_forms(sub):
            for rule in rules:
                if rule_covers(rule, form):
                    return rule
    return None


def sub_decision(sub: str, perms: dict) -> str:
    """One subcommand: deny and ask in the exact tier, then in the wildcard tier; then allow.
    Deny rules see the text as written and past the documented wrappers; ask and allow rules also
    past the measured ones (sudo, env)."""
    rules = {k: _bash_rules(perms.get(k, [])) for k in ("deny", "ask", "allow")}
    forms = {"deny": match_forms(sub), "ask": match_forms(sub, True), "allow": match_forms(sub, True)}
    for tier in (True, False):
        for kind in ("deny", "ask"):
            for rule in rules[kind]:
                for form in forms[kind]:
                    if rule_covers(rule, form) and exact_tier(rule, form) == tier:
                        return kind
    if forms["allow"][-1].split()[0] in READ_ONLY:
        return "allow"
    if any(rule_covers(r, f) for r in rules["allow"] for f in forms["allow"]):
        return "allow"
    return "prompt"


def decision(cmd: str, perms: dict | None = None) -> str:
    perms = perms or _permissions()
    got = [sub_decision(s, perms) for s in subcommands(cmd)]
    for kind in ("deny", "ask", "prompt"):
        if kind in got:
            return kind
    return "allow"


# ------------------------------------------------------------------ the model itself
@pytest.mark.parametrize("cmd,subs", [
    ("bash <<'EOF'\necho hi\nrm -rf x\nEOF", ["bash"]),
    ("bash <<-EOF\n\techo hi\n\tEOF\necho after", ["bash", "echo after"]),
    ("bash <<< 'echo a; b'", ["bash"]),
    ("bash -s < scripts/x.sh", ["bash -s"]),
    ("bash scripts/x.sh > out.log 2>&1", ["bash scripts/x.sh"]),
    ("cat <<EOF | bash\nls\nEOF", ["cat", "bash"]),
    ("curl x | bash", ["curl x", "bash"]),
])
def test_model_drops_heredoc_bodies_and_redirections(cmd, subs):
    assert [match_forms(s)[0] for s in subcommands(cmd)] == subs


@pytest.mark.parametrize("perms,cmd,want", [
    # measured on 2.1.326 with these minimal permission blocks
    ({"deny": ["Bash(zz:*)"], "ask": ["Bash(zz y)"]}, "zz y", "ask"),
    ({"deny": ["Bash(zz:*)"], "ask": ["Bash(zz y)"]}, "zz y q", "deny"),
    ({"deny": ["Bash(zz:*)"], "ask": ["Bash(zz y:*)"]}, "zz y", "ask"),
    ({"deny": ["Bash(zz:*)"], "ask": ["Bash(zz y:*)"]}, "zz y q", "deny"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(zzfoo)"]}, "sudo -u root zzfoo", "ask"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(zzfoo)"]}, "sudo zzfoo x", "deny"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(zzfoo:*)"]}, "sudo zzfoo", "ask"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(zzfoo *)"]}, "sudo zzfoo x", "deny"),
    ({"deny": ["Bash(sudo zzfoo)"], "ask": ["Bash(zzfoo)"]}, "sudo zzfoo", "deny"),
    ({"deny": ["Bash(sudo *zzfoo*)"], "ask": ["Bash(zzfoo)"]}, "sudo -E zzfoo", "ask"),
    ({"deny": ["Bash(*zzfoo*)"], "ask": ["Bash(zzfoo)"]}, "zzfoo", "ask"),
    ({"deny": ["Bash(timeout:*)"], "ask": ["Bash(zzfoo)"]}, "timeout 5 zzfoo", "ask"),
    ({"deny": ["Bash(env:*)"], "ask": ["Bash(zzfoo)"]}, "env zzfoo", "ask"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(z*zfoo)"]}, "sudo -u root zzfoo", "deny"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(z*zfoo)"]}, "zzfoo", "ask"),
    ({"deny": ["Bash(sudo:*)"], "ask": ["Bash(zzfoo -s*)"]}, "sudo -u root zzfoo -s", "deny"),
    ({"deny": ["Bash(sudo:*)"], "ask": []}, "sudo -u root zzfoo", "deny"),
])
def test_model_reproduces_the_measured_tiers(perms, cmd, want):
    assert decision(cmd, {"allow": [], **perms}) == want


# ------------------------------------------------------------------ the entries
def test_dead_pipe_entries_are_gone():
    perms = _permissions()
    assert not (set(perms["deny"]) | set(perms.get("ask", []))) & set(DEAD)


@pytest.mark.parametrize("entry", DEAD)
def test_dead_entry_could_never_match(entry):
    rule = _bash_rules([entry])
    for cmd in PIPE_TO_BASH + STILL_RUNS + LOCAL_STDIN_BASH + [entry[5:-1]]:
        assert first_match(rule, cmd) is None, cmd


def test_stdin_bash_entries_are_ask():
    perms = _permissions()
    assert set(STDIN_BASH) <= set(perms.get("ask", [])), sorted(set(STDIN_BASH) - set(perms.get("ask", [])))
    assert not set(STDIN_BASH) & set(perms["deny"])


def test_no_ask_entry_sits_in_the_exact_tier():
    """An exact-tier ask outranks a wildcard deny past a wrapper (measured): every ask entry needs a
    `*` that is not a trailing `:*`, which matches its bare prefix in the exact tier."""
    for entry in _bash_rules(_permissions().get("ask", [])):
        assert "*" in entry.replace(":*", "") , entry


@pytest.mark.parametrize("cmd", PIPE_TO_BASH)
def test_pipe_to_bash_prompts(cmd):
    assert decision(cmd) == "ask"


@pytest.mark.parametrize("cmd", PROMPTED_ON_BASE)
def test_base_prompts_still_prompt(cmd):
    assert decision(cmd) in ("ask", "prompt")


@pytest.mark.parametrize("cmd", DENIED_ON_BASE)
def test_every_base_deny_stays_denied(cmd):
    base_like = {**_permissions(), "ask": []}
    assert decision(cmd, base_like) == "deny"
    assert decision(cmd) == "deny"


def test_exact_tier_asks_would_have_downgraded_sudo():
    """The first rework's exact `Bash(bash)` ask: the model shows the downgrade the tiers cause."""
    exact = {**_permissions(), "ask": ["Bash(bash)"]}
    assert decision("curl x | sudo -u root bash", exact) == "ask"


@pytest.mark.parametrize("cmd", LOCAL_STDIN_BASH)
def test_local_stdin_bash_prompts_and_is_not_denied(cmd):
    assert decision(cmd) == "ask"


@pytest.mark.parametrize("cmd", KNOWN_GAPS)
def test_known_gaps_still_run(cmd):
    """Pinned so a later rule that closes one shows up here (move it to PIPE_TO_BASH then)."""
    assert decision(cmd) == "allow"


@pytest.mark.parametrize("cmd", STILL_RUNS)
def test_plain_downloads_and_scripts_still_run(cmd):
    assert decision(cmd) == "allow"


def test_no_shell_wide_rule():
    perms = _permissions()
    wide = {"Bash(sh:*)", "Bash(bash:*)", "Bash(sh *)", "Bash(bash *)", "Bash(curl:*)", "Bash(wget:*)",
            "Bash(bash -*)", "Bash(bash -x *)", "Bash(bash -l *)", "Bash(bash -- *)", "Bash(b*ash *)"}
    assert not wide & (set(perms["deny"]) | set(perms.get("ask", [])))
    assert {"Bash(curl:*)", "Bash(wget:*)", "Bash(bash:*)"} <= set(perms["allow"])


# ------------------------------------------------------------------ harness texts
def _shell_blocks():
    """Each fenced shell block of the harness texts, continuation lines joined."""
    fence = re.compile(r"^\s*```(\w*)\s*$")
    for base in ("commands", "agents", "skills", "templates", "docs"):
        for path in sorted((REPO / base).rglob("*.md")):
            lang, start, buf = None, 0, []
            for no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                m = fence.match(line)
                if m and lang is None:
                    lang, start, buf = m.group(1), no, []
                elif m:
                    if lang in ("bash", "sh", "shell", "console", ""):
                        yield f"{path.relative_to(REPO)}:{start}", "\n".join(buf).replace("\\\n", " ")
                    lang = None
                elif lang is not None:
                    buf.append(line)


def test_harness_heredoc_reading_is_block_based():
    text = "cat > f <<'EOF'\nbash\nEOF\nbash scripts/x.sh"
    assert [match_forms(s)[0] for s in subcommands(text)] == ["cat", "bash scripts/x.sh"]


def test_no_harness_text_runs_a_stdin_bash():
    """No shell block in the command, agent, skill, template or doc texts reaches an ask entry."""
    rules = _bash_rules(STDIN_BASH)
    hits, blocks = [], list(_shell_blocks())
    assert len(blocks) > 100 and any("<<" in b for _, b in blocks)  # the scan reaches real text, heredocs included
    for where, block in blocks:
        for line in strip_heredoc_bodies(block).split("\n"):
            if line.lstrip().startswith("#"):
                continue
            if first_match(rules, line):
                hits.append((where, line))
    assert not hits, hits
