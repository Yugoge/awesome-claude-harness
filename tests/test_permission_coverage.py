"""Every Bash command the command, agent and skill texts run through the harness home keeps the allow
entry that covers it (P2 R6/R17, D14: entries are respelled, none granted or withdrawn).

The texts name the harness home through one channel, `"${CLAUDE_HOME:-$HOME/.claude}/..."`, and the
allow list's harness entries are spelled the same way, because the CLI matches a Bash rule against the
literal command text (code.claude.com/docs/en/permissions, Bash rules: no `~` or variable expansion; a
rule `P:*` matches `P` and `P <args>`; a compound command is split at `&&`, `||`, `;`, `|`, `&` and
newlines and each part must be allowed). The cases model that prefix rule:

* each simple command of a rewritten line that starts a program from the harness home (`python3`,
  `bash`, ...) has a covering entry (its respelled entry, or `Bash(python3:*)` / `Bash(bash:*)`);
* no rewritten command loses coverage: whatever its old `~/.claude` spelling was covered by under the
  old list (this list with its harness entries spelled back), the new spelling is covered by this list;
* a running session reloads `permissions` when settings.json changes (code.claude.com/docs/en/settings)
  while a command already in flight keeps the old text it loaded, so the old spelling of every
  rewritten command stays covered by this list too; RUNNING_SESSION_SPELLINGS are the old entries kept
  for that, each beside its successor, to be removed once no session predates the respelling.

An entry is not the whole decision. The CLI parses the line first (measured on Claude Code 2.1.319 with its own
permission check, the binary's embedded code run offline): a parameter expansion it cannot resolve, any `${...}`
and any `$NAME` but `$HOME`, makes the whole line ask unless an allow entry is that whole line, so no prefix
entry covers a channel-spelled line that takes arguments. A command text's line whose old spelling the CLI
allowed therefore names the harness home through the root the harness command prints, `<HARNESS_ROOT>` (R1's
`HARNESS_ROOT=` line, the hook's own install: CLAUDE_HOME or not, any repository), which the session writes as
the literal path; the channel stays where the old spelling asked as well. `cli_allows` models that decision
and the last case holds every command text to it. A subagent gets the same root as its start context
(prompt-workflow.py at SubagentStart, P2-3), so the agent texts and the prompt includes they read are held to
it line by line too; ASKS_SINCE_P2 are the agent lines still on the channel that 2.1.319 measured asking.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHANNEL = "${CLAUDE_HOME:-$HOME/.claude}"
ROOT = "<HARNESS_ROOT>/"  # the printed root, which the session writes as the literal path
RUN_ROOT = '"' + ROOT  # a command's operand spelled through it (a bare one is a Read path or a name in prose)
OLD = "~/.claude/"
PROGRAMS = {"python3", "python", "bash", "sh"}
SHELL_LANGS = {"", "bash", "sh", "shell", "text", "console"}

# The old `~/.claude` spellings kept beside their successors for sessions that loaded command text
# before the respelling: P10's Exp 6 under Claude Code 2.1.319's own Bash permission check, over
# origin/master's command, agent and skill lines and DELETED_OLD_LINES (product and harness-home cwd):
# each one allows a line that asks without it.
RUNNING_SESSION_SPELLINGS = [
    "Bash(~/.claude/scripts/check-overnight-reports.sh:*)",
    "Bash(~/.claude/scripts/orchestrator.sh clean-inspect:*)",
    "Bash(~/.claude/scripts/orchestrator.sh clean-merge-reports:*)",
]

# Old spellings P10's Exp 6 deleted: replayed through 2.1.319's Bash permission check, no line of
# origin/master's texts starts asking without them, for one of two reasons. A line that runs its script
# after `source ~/.claude/venv/bin/activate &&` asks at that part ("'source' evaluates arguments as
# shell code"), with or without them; a line that passes a shell variable (`"$PROJECT_ROOT"`, any `$NAME`
# but `$HOME`, any `${...}`) asks ("A variable in this command can't be checked before it runs"), with or
# without them.
EXP6_DELETED_SPELLINGS = [
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-enrich.py:*)",
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-maintain.py:*)",
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-query.py:*)",
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/spec-verify/spec-verify.py:*)",
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/todo/clean.py:*)",
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/todo/close.py:*)",
    "Bash(source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/todo/test.py:*)",
    "Bash(~/.claude/scripts/detect-orphan-agents.sh:*)",
    "Bash(~/.claude/scripts/detect-orphan-commands.sh:*)",
    "Bash(~/.claude/scripts/detect-orphan-scripts.sh:*)",
    "Bash(~/.claude/scripts/orchestrator.sh record-checkpoint:*)",
    "Bash(~/.claude/scripts/orchestrator.sh rule-inspect:*)",
    "Bash(~/.claude/scripts/scan-project.sh:*)",
]


# ------------------------------------------------------------------ the CLI's prefix rule
def bash_rules(allow: list[str]) -> list[str]:
    return [e[5:-1] for e in allow if e.startswith("Bash(") and e.endswith(")")]


def rule_covers(rule: str, cmd: str) -> bool:
    """`P:*` (or `P *`) matches `P` and `P <args>`; any other `*` matches any text; else exact."""
    if rule.endswith(":*"):
        rule = rule[:-2] + " *"
    if "*" not in rule:
        return cmd == rule
    if rule.endswith(" *") and rule.count("*") == 1 and cmd == rule[:-2]:
        return True
    rx = ".*".join(re.escape(part) for part in rule.split("*"))
    return re.fullmatch(rx, cmd, re.S) is not None


def covering(rules: list[str], *cmds: str) -> str | None:
    for rule in rules:
        if any(rule_covers(rule, c) for c in cmds):
            return rule
    return None


# ------------------------------------------------------------------ the old spelling
def tilde(text: str) -> str:
    """The channel, or the printed root, spelled back as `~/.claude/`."""
    text = re.sub(r'"(?:\$\{CLAUDE_HOME:-\$HOME/\.claude\}|<HARNESS_ROOT>)/([^"]*)"', r"~/.claude/\1", text)
    return text.replace(CHANNEL + "/", OLD).replace(ROOT, OLD)


def old_rule(rule: str) -> str:
    """An entry's old spelling: a directly run harness script gained `bash` in the respelling."""
    return re.sub(r"^bash (~/\.claude/scripts/\S+?\.sh)(?=[\s:]|$)", r"\1", tilde(rule))


def old_spellings(cmd: str) -> list[str]:
    """A rewritten command's two candidate old spellings: as written, and, for a script it now runs
    through an interpreter, run directly (both the same for a line still in the old spelling)."""
    if CHANNEL not in cmd and RUN_ROOT not in cmd:
        return [cmd, cmd]
    text = tilde(cmd)
    bare = re.sub(r"^(?:bash|python3) (~/\.claude/scripts/\S+?\.(?:sh|py))(?=\s|$)", r"\1", text)
    return [text, bare]


def old_rules(rules: list[str]) -> list[str]:
    return list(dict.fromkeys(old_rule(r) for r in rules))


# ------------------------------------------------------------------ the texts' Bash commands
def _texts() -> list[Path]:
    return sorted([*REPO.glob("commands/*.md"), *REPO.glob("agents/*.md"), *REPO.glob("skills/*/SKILL.md"),
                   *REPO.glob("templates/prompt-includes/*.md")])


def shell_commands(md: str):
    """(line, command) for each logical line of a shell fence (continuations joined, heredoc bodies and
    comment or data lines left out) and each inline code span outside fences."""
    lines = md.split("\n")
    i, fence = 0, None
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^\s*```+\s*([\w-]*)", line)
        if m:
            fence = None if fence is not None else m.group(1).lower()
            i += 1
            continue
        if fence is None:
            for span in re.findall(r"`([^`\n]+)`", line):
                yield i + 1, span.strip()
            i += 1
            continue
        if fence not in SHELL_LANGS:
            i += 1
            continue
        start, text = i + 1, line
        while text.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            text = text.rstrip()[:-1] + " " + lines[i].strip()
        i += 1
        tag = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", text)
        if tag:
            while i < len(lines) and lines[i].strip() != tag.group(1):
                i += 1
            i += 1
        body = text.strip()
        if body and not body.startswith(("#", '"', "{", "}", "//", "|")):
            yield start, body


def _scan(text: str, i: int, close: str) -> int:
    """Index just past the `close` that ends the construct opened before `i` (quotes and $( ) nest)."""
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if close in ('"', "'") and c == close:
            return i + 1
        if close == "'":
            i += 1
            continue
        if text.startswith("$(", i):
            i = _scan(text, i + 2, ")")
            continue
        if close == ")" and c == ")":
            return i + 1
        if close != '"' and c in "'\"":
            i = _scan(text, i + 1, c)
            continue
        i += 1
    return i


def simple_commands(cmd: str) -> list[str]:
    """The simple commands of a command line: split at top-level separators, each `$( )` body too."""
    out, cur, i = [], "", 0
    while i < len(cmd):
        if cmd.startswith("$(", i):
            j = _scan(cmd, i + 2, ")")
            out += simple_commands(cmd[i + 2:j - 1])
            cur += cmd[i:j]
            i = j
            continue
        c = cmd[i]
        if c in "'\"":
            j = _scan(cmd, i + 1, c)
            if c == '"':
                for k in re.finditer(r"\$\(", cmd[i:j]):
                    end = _scan(cmd[i:j], k.end(), ")")
                    out += simple_commands(cmd[i:j][k.end():end - 1])
            cur += cmd[i:j]
            i = j
            continue
        sep = re.match(r"&&|\|\||\|&|[;|&\n]", cmd[i:])
        if sep:
            out.append(cur)
            cur, i = "", i + len(sep.group(0))
            continue
        cur += c
        i += 1
    out.append(cur)
    words = []
    for s in out:
        s = s.strip().lstrip("({").rstrip(")}").strip()
        s = re.sub(r"^(?:(?:if|then|else|elif|do|while|until|!)\s+)+", "", s)
        s = re.sub(r"\s+\d?>(?:&\d|\s*/dev/null)$", "", s)
        if s and not _assignment_only(s):
            words.append(s)
    return words


def _assignment_only(s: str) -> bool:
    """`NAME=value` with no command after it (its `$( )` bodies are commands of their own)."""
    m = re.match(r"[A-Za-z_]\w*=", s)
    if not m:
        return False
    i = m.end()
    while i < len(s) and not s[i].isspace():
        if s[i] in "'\"":
            i = _scan(s, i + 1, s[i])
        elif s.startswith("$(", i):
            i = _scan(s, i + 2, ")")
        else:
            i += 1
    return not s[i:].strip()


def _names_home(text: str) -> bool:
    return CHANNEL in text or RUN_ROOT in text or OLD in text


def rewritten_commands():
    """(file:line, logical line, simple command) for each simple command naming the harness home."""
    for path in _texts():
        for n, line in shell_commands(path.read_text(encoding="utf-8")):
            if not _names_home(line):
                continue
            for simple in simple_commands(line):
                if _names_home(simple):
                    yield f"{path.relative_to(REPO)}:{n}", line, simple


# ------------------------------------------------------------------ the CLI's decision for a whole line
# A parameter expansion the CLI cannot resolve before the command runs (it resolves `~` and `$HOME` only).
UNCHECKABLE = re.compile(r"\$\{|\$(?!HOME\b)[A-Za-z_]")
# Programs the CLI runs unasked on reads it allows (the harness home among them), no entry needed.
READ_ONLY = {"cat", "ls", "head", "tail", "wc", "echo", "printf", "pwd", "true"}


def filled(text: str) -> str:
    """A line as the session writes it: the printed root as a literal path, any other `<placeholder>` a word."""
    text = text.replace(ROOT, "/harness-root/")
    return re.sub(r"<([A-Za-z_][^<>\n]*)>", lambda m: "ph" + re.sub(r"\W", "", m.group(1)), text)


def cli_allows(rules: list[str], line: str) -> bool:
    """The CLI's decision: an entry that is the whole line allows it; else a line with an expansion it cannot
    resolve asks; else each simple command needs a covering entry or is a read-only program."""
    line = filled(line)
    if line.strip() in rules:
        return True
    if UNCHECKABLE.search(line):
        return False
    return all(covering(rules, s) is not None or s.split()[0] in READ_ONLY for s in simple_commands(line))


def _allow() -> list[str]:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]


# ------------------------------------------------------------------ the cases
def test_the_allow_list_spells_the_harness_home_through_the_channel():
    allow = _allow()
    old = [e for e in allow if OLD in e]
    assert old == [e for e in RUNNING_SESSION_SPELLINGS if e in allow] and set(old) == set(RUNNING_SESSION_SPELLINGS)
    successors = {old_rule(r): r for r in bash_rules(allow) if CHANNEL in r}
    for entry in old:
        assert entry[5:-1] in successors, f"{entry} is kept for running sessions without its successor"
        assert allow.index(entry) == allow.index("Bash(%s)" % successors[entry[5:-1]]) + 1
    assert len(allow) == len(set(allow))


def test_every_harness_program_line_has_its_covering_entry():
    rules = bash_rules(_allow())
    seen, missing = 0, []
    for where, line, simple in rewritten_commands():
        if (CHANNEL not in simple and RUN_ROOT not in simple) or simple.split()[0] not in PROGRAMS:
            continue
        seen += 1
        if covering(rules, line, simple) is None:
            missing.append(f"{where}: {simple}")
    assert seen > 100 and not missing, "\n".join(missing)


def test_no_rewritten_command_loses_its_permission():
    rules = bash_rules(_allow())
    before = old_rules(rules)
    lost = []
    for where, line, simple in rewritten_commands():
        was = covering(before, *old_spellings(line), *old_spellings(simple))
        if was and covering(rules, line, simple) is None:
            lost.append(f"{where}: {simple} (was {was})")
    assert not lost, "\n".join(lost)


def test_a_running_session_keeps_the_old_spellings_it_loaded():
    rules = bash_rules(_allow())
    before = [r for r in old_rules(rules) if "Bash(%s)" % r not in EXP6_DELETED_SPELLINGS]
    asks = []
    for where, line, simple in rewritten_commands():
        old = (old_spellings(line)[0], old_spellings(simple)[0])
        if covering(before, *old) and covering(rules, *old) is None:
            asks.append(f"{where}: {old[1]}")
    assert not asks, "\n".join(asks)


def test_exp6_deleted_spellings_decided_no_line():
    """Each old line an Exp 6 deleted spelling covers asks under 2.1.319 with or without it: it has a
    part `source ~/.claude/venv/bin/activate`, which no entry covers, or a shell variable the CLI
    cannot check before the command runs."""
    allow = _allow()
    activate = "source ~/.claude/venv/bin/activate"
    assert covering(bash_rules(allow), activate) is None
    seen = []
    for entry in EXP6_DELETED_SPELLINGS:
        assert entry not in allow
        for where, line, _simple in rewritten_commands():
            old = old_spellings(line)[0]
            if rule_covers(entry[5:-1], old):
                seen.append(where)
                assert activate in simple_commands(old) or UNCHECKABLE.search(old), f"{where}: {old}"
    assert seen


# Old lines a running session can still hold whose text P1b's G2 arming deleted from today's
# commands (origin/master's commands/dev-overnight.md ran it at Steps 2, 3 and 4), so no rewritten
# line stands for them.
DELETED_OLD_LINES = [
    ("commands/dev-overnight.md (origin/master, Steps 2-4)",
     "~/.claude/scripts/check-overnight-reports.sh docs/dev/overnight/<session_id>"),
]


def test_each_kept_old_spelling_covers_a_line_only_it_covers():
    """Each kept entry covers the old spelling (as written, or with the script run directly, as the
    old text ran it) of a line the texts run, or of a deleted line a running session still holds,
    which no other entry covers."""
    allow = _allow()
    rows = list(rewritten_commands()) + [(where, line, line) for where, line in DELETED_OLD_LINES]
    for entry in RUNNING_SESSION_SPELLINGS:
        others = bash_rules([e for e in allow if e != entry])
        needed = [where for where, line, simple in rows
                  for old in zip(old_spellings(line), old_spellings(simple))
                  if rule_covers(entry[5:-1], old[0]) or rule_covers(entry[5:-1], old[1])
                  if covering(others, *old) is None]
        assert needed, f"{entry} covers no old spelling a running session holds"


# The start-function fallback runs exactly when the hook output, and with it the HARNESS_ROOT= line,
# is gone (a compaction removed it or the hook printed none), so no printed root can fill it: it keeps
# the channel and asks rather than fail (P1c's dev_command ctx=compact and ctx=noid replays).
NO_PRINTED_ROOT = ('python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/prompt-workflow.py" start',)


def test_no_line_the_cli_allowed_in_its_old_spelling_asks_now():
    """Each command text's harness line the CLI allowed in its old spelling under the old list, both as written and
    with the script run directly (whichever the old text ran), is allowed by the CLI now: a `${...}` channel on it
    would ask. Agent and prompt-include texts have their own case (test_no_agent_line_the_cli_allowed_before_asks_now);
    the start-function fallback (NO_PRINTED_ROOT) is outside."""
    rules = bash_rules(_allow())
    before = old_rules(rules)
    asks = []
    for where, line in dict.fromkeys((where, line) for where, line, _ in rewritten_commands()):
        if not where.startswith("commands/") or line.startswith(NO_PRINTED_ROOT):
            continue
        if all(cli_allows(before, old) for old in old_spellings(line)) and not cli_allows(rules, line):
            asks.append(f"{where}: {line}")
    assert not asks, "\n".join(asks)


# ------------------------------------------------------------------ agent and prompt-include texts
# The agent lines that ran unasked in origin/master's spelling and ask under 2.1.319 on the channel: PR #10
# c6717051862's 13 lines (P2-3; dev.md:1087's and qa.md:1936's spec-check line is checkpoint-marking.md's now),
# re-measured through 2.1.319 headless from a product repository with the root its SubagentStart context
# carries (channel: asks; `<HARNESS_ROOT>` filled and `~/.claude`: run). Each is written with the harness home
# as {H}. Which spelling origin/master ran is history the texts no longer hold, so `old_spellings`' both-forms
# model misses these `python3` and `bash` lines; the cases take them from this measurement.
ASKS_SINCE_P2 = [
    ("agents/changelog-analyst.md", 'python3 "{H}/scripts/write-push-gate-token.py" --repo-root "<GIT_ROOT>" '
                                    '--branch "<BRANCH>" --commit "<COMMIT_SHA>"'),
    ("agents/cleaner.md", 'python3 "{H}/scripts/write-push-gate-token.py" --repo-root "<GIT_ROOT>" '
                          '--branch "<BRANCH>" --commit "<COMMIT_SHA>"'),
    ("agents/dev.md", 'ls -la "{H}/scripts/"'),
    ("agents/dev.md", 'cat "{H}/scripts/orchestrator.sh"'),
    ("agents/dev.md", 'cat "{H}/scripts/check-file-references.sh"'),
    ("agents/pm.md", 'bash "{H}/scripts/overnight-status.sh"'),
    ("agents/qa.md", 'python3 "{H}/scripts/blast-radius-tool.py"  --git-diff --base HEAD  --output /dev/stdout  '
                     '--task-id <task_id>'),
    ("agents/spec.md", 'python3 "{H}/scripts/spec-check.py"'),
    ("agents/spec.md", 'python3 "{H}/scripts/spec-verify/spec-verify-views.py"'),
    ("agents/spec.md", 'python3 "{H}/scripts/spec-verify/spec-verify.py"'),
    ("agents/test-executor.md", 'ls "{H}/venv/bin/activate"'),
    ("agents/test-executor.md", 'python3 -m venv "{H}/venv"'),
    ("templates/prompt-includes/checkpoint-marking.md", 'python3 "{H}/scripts/spec-check.py"'),
]
# The lines lane L3 has still to respell: each case is a strict xfail until L3 writes its harness home as
# `<HARNESS_ROOT>`; when one XPASSes, delete its entry here (ASKS_SINCE_P2 keeps holding the line).
L3_TO_RESPELL = list(ASKS_SINCE_P2)
L3_PENDING = "P2-3, lane L3: write this line's harness home as <HARNESS_ROOT>, then remove this marker"


def _key(file: str, line: str) -> tuple[str, str]:
    """A line's file and text with the harness home as {H} in either spelling and no leading `python3` (the
    include names spec-check.py without its interpreter), so a case keeps its key through L3's respelling."""
    text = line.replace(CHANNEL + "/", "{H}/").replace(ROOT, "{H}/")
    return file, re.sub(r"^python3 ", "", text)


MEASURED = {_key(*entry) for entry in ASKS_SINCE_P2}
PENDING = {_key(*entry) for entry in L3_TO_RESPELL}


def agent_lines() -> list[tuple[str, str]]:
    """(file:line, logical line) of each agent and prompt-include line naming the harness home."""
    return list(dict.fromkeys((where, line) for where, line, _ in rewritten_commands()
                              if where.startswith(("agents/", "templates/prompt-includes/"))))


def _agent_cases():
    seen: dict[str, int] = {}
    for where, line in agent_lines():
        seen[where] = seen.get(where, 0) + 1
        pending = _key(where.rsplit(":", 1)[0], line) in PENDING
        yield pytest.param(where, line, id=f"{where}#{seen[where]}",
                           marks=[pytest.mark.xfail(strict=True, reason=L3_PENDING)] if pending else [])


@functools.lru_cache(maxsize=None)
def _rule_lists() -> tuple[list[str], list[str]]:
    rules = bash_rules(_allow())
    return rules, old_rules(rules)


@pytest.mark.parametrize("where, line", list(_agent_cases()))
def test_no_agent_line_the_cli_allowed_before_asks_now(where, line):
    """An agent or prompt-include line the CLI allowed in its old spelling (ASKS_SINCE_P2, else both forms by
    `old_spellings`) is allowed now: it names the harness home through the root its start context carries."""
    rules, before = _rule_lists()
    was = (_key(where.rsplit(":", 1)[0], line) in MEASURED
           or all(cli_allows(before, old) for old in old_spellings(line)))
    assert not was or cli_allows(rules, line), f"{where}: {line}"


def test_each_measured_agent_line_is_in_the_texts():
    keys = {_key(where.rsplit(":", 1)[0], line) for where, line in agent_lines()}
    assert not [entry for entry in ASKS_SINCE_P2 if _key(*entry) not in keys]
    assert set(L3_TO_RESPELL) <= set(ASKS_SINCE_P2)


@pytest.mark.xfail(strict=True, reason="P2-3, integration: settings.json registers prompt-workflow.py at "
                                       "SubagentStart, then remove this marker")
def test_a_subagent_starts_with_the_printed_root():
    """The agent lines' `<HARNESS_ROOT>` reaches a subagent only through prompt-workflow.py's SubagentStart answer
    (hooks/tests/test_prompt_workflow_subagent_roots.py), registered for every agent type."""
    groups = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["hooks"].get("SubagentStart", [])
    assert any(group.get("matcher", "") in ("", "*")
               and any(h.get("command", "").endswith('/hooks/prompt-workflow.py"') for h in group["hooks"])
               for group in groups)


def test_the_cli_decision_model():
    """Cases measured with Claude Code 2.1.319's own permission check (P2's coverage experiment)."""
    assert not cli_allows(["python3:*"], 'python3 "%s/scripts/x.py" --task-id t' % CHANNEL)
    assert not cli_allows(['python3 "%s/scripts/x.py":*' % CHANNEL], 'python3 "%s/scripts/x.py" --a b' % CHANNEL)
    assert cli_allows(['python3 "%s/scripts/x.py"' % CHANNEL], 'python3 "%s/scripts/x.py"' % CHANNEL)
    assert cli_allows(["python3:*"], 'python3 "<HARNESS_ROOT>/scripts/x.py" --task-id <task_id>')
    assert cli_allows(["python3:*"], 'python3 "$HOME/.claude/scripts/x.py"')
    assert cli_allows(["python3:*"], "python3 ~/.claude/scripts/x.py --a b")
    assert not cli_allows(["python3:*"], 'python3 ~/.claude/scripts/x.py "$TASK_ID"')
    assert cli_allows([], 'cat "<HARNESS_ROOT>/scripts/orchestrator.sh"')
    assert not cli_allows([], "npm install")
    assert cli_allows(["bash:*"], 'DEFAULT_BRANCH=$(bash "<HARNESS_ROOT>/scripts/derive-default-branch.sh")')
    assert old_spellings('bash "<HARNESS_ROOT>/scripts/x.sh" a') == ["bash ~/.claude/scripts/x.sh a",
                                                                     "~/.claude/scripts/x.sh a"]


def test_the_prefix_rule_model():
    assert rule_covers("python3:*", 'python3 "%s/scripts/x.py" --a' % CHANNEL)
    assert rule_covers("python3:*", "python3")
    assert not rule_covers("python3:*", "python3x y")
    assert rule_covers('bash "%s/scripts/x.sh":*' % CHANNEL, 'bash "%s/scripts/x.sh" --task-id t' % CHANNEL)
    assert not rule_covers('bash "%s/scripts/x.sh":*' % CHANNEL, 'bash "%s/scripts/x.sh2"' % CHANNEL)
    assert rule_covers("source venv/bin/activate && python*", "source venv/bin/activate && python3 a.py")
    assert simple_commands('A="$(python3 "%s/s.py" x)" && eval "$A" || { echo no; }' % CHANNEL) == [
        'python3 "%s/s.py" x' % CHANNEL, 'eval "$A"', "echo no"]
    assert old_spellings('bash "%s/scripts/x.sh" a' % CHANNEL) == ["bash ~/.claude/scripts/x.sh a",
                                                                   "~/.claude/scripts/x.sh a"]
    assert old_rule('bash "%s/scripts/x.sh" sub:*' % CHANNEL) == "~/.claude/scripts/x.sh sub:*"
    assert old_rule('python3 "%s/scripts/y.py":*' % CHANNEL) == "python3 ~/.claude/scripts/y.py:*"
    assert old_spellings('source "%s/venv/bin/activate" && python3 "%s/scripts/y.py"' % (CHANNEL, CHANNEL)) == [
        "source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/y.py"] * 2
