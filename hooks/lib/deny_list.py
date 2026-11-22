"""The deny list that was Claude Code's own (settings.json permissions.deny), matched as the CLI matched it.

The CLI applied its deny entries after the hooks, over a hook's allow, with no hook event and no record, so an
owner's /allow could not release them. The entries now live in policies/cli-deny.v1.json and this module decides
them for the pre-tool rule hooks/pretool-deny-list.py, whose refusal the launcher records and an /allow grant
releases like every other. ``entries`` is the one reader of what is on the list (the policy file plus the two
switch rules that stay in settings.json), for this rule and hooks/permissionrequest-answer.py; ``Policy``
prepares the patterns once per hook run; ``refusal`` answers one payload.

Matching, as the CLI's (the models: tests/test_permission_pipe_to_shell.py for Bash, tests/test_secret_file_denies.py
and tests/test_home_secret_denies.py for paths, hooks/tests/test_skill_deny_coverage.py for Skill):
- Bash(P): the command split into subcommands at && || ; | |& & and newlines outside quotes (heredoc bodies
  dropped); each subcommand without its redirections, then past the wrappers timeout/nice/stdbuf/time/nohup/
  command/builtin/noglob and leading assignments; `P:*` at the end is `P` or `P <args>`, any other `*` any text.
- Read(G) / Edit(G): gitignore syntax, case-insensitive; `//p` absolute, `~/p` under the home, `/p` under the
  settings source (the harness home), else under the current directory (a bare name at any depth); a pattern
  naming a directory covers what is below it; per tool list the last matching entry wins and `!G` lifts. Read
  holds Read, Grep and Glob; Edit, Write, MultiEdit and NotebookEdit are held to both lists. In Bash, the
  operands of the plain file readers are held to the Read list and output redirection or tee targets to both.
- Skill(N): the skill name, a leading `/` dropped, equal to N.
"""
from __future__ import annotations

import json
import os
import re

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME_DIR = os.path.dirname(HOOKS)                        # the harness home: the settings source
POLICY = os.path.join(HOME_DIR, "policies", "cli-deny.v1.json")
SETTINGS = os.path.join(HOME_DIR, "settings.json")
KEPT = ("a rule of the harness switch, kept in settings.json's permissions.deny so that it also holds while the "
        "harness is off")

DOC_WRAPPERS = re.compile(r"^(?:(?:timeout|nice|stdbuf)(?:\s+-\S+)*(?:\s+\d\S*)?|time|nohup|command|builtin|noglob)\s+")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")
REDIRECT = re.compile(r"""\s*\d*(?:<<<|<<-?|&>>|&>|>>|>&|<&|<>|>\||>|<(?!\())\s*(?:'[^']*'|"[^"]*"|[^\s;&|<>]+)""")
OUT_TARGET = re.compile(r"""(?:^|\s)\d*(?:&>>|&>|>>|>\||>)(?!&)\s*('[^']*'|"[^"]*"|[^\s;&|<>]+)""")
HEREDOC = re.compile(r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")
READERS = frozenset({"cat", "head", "tail", "less", "more", "tac", "nl", "wc", "sort", "uniq", "strings", "xxd",
                     "od", "base64", "diff"})
READ_TOOLS = {"Read": "file_path", "Grep": "path", "Glob": "path"}
WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}


def _strip_heredoc_bodies(text: str) -> str:
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


def subcommands(cmd: str) -> list:
    cmd = _strip_heredoc_bodies(cmd)
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
            parts.append(cur); cur = ""; i += 1  # noqa: E702
        elif ch == "&" and (cmd[i - 1:i] in (">", "<") or cmd[i + 1:i + 2] == ">"):
            cur += ch
        elif ch in ";|&\n":
            parts.append(cur); cur = ""  # noqa: E702
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def match_forms(sub: str) -> list:
    cur = re.sub(r"\s+", " ", REDIRECT.sub("", sub)).strip()
    forms = [cur]
    while True:
        nxt = ASSIGN.sub("", DOC_WRAPPERS.sub("", cur, count=1), count=1)
        if nxt == cur:
            return forms
        forms.append(nxt)
        cur = nxt


def _bash_matcher(rule: str):
    """(exact text, compiled wildcard regex or None) for a Bash(...) body."""
    if rule.endswith(":*"):
        rule = rule[:-2] + " *"
    if "*" not in rule:
        return rule, None
    bare = rule[:-2] if rule.endswith(" *") else None
    return bare, re.compile(".*".join(re.escape(p) for p in rule.split("*")), re.S)


def _glob(pattern: str):
    """A gitignore pattern -> (anchor, regex over the path below the anchor, dir_only)."""
    dir_only = pattern.endswith("/") and not pattern.endswith("**/")
    pattern = pattern.rstrip("/") if dir_only else pattern
    if pattern.startswith("//"):
        anchor, body, prefix = "/", pattern[2:], ""
    elif pattern.startswith("~/"):
        anchor, body, prefix = "~", pattern[2:], ""
    elif pattern.startswith("/"):
        anchor, body, prefix = "src", pattern[1:], ""
    else:
        body = pattern[2:] if pattern.startswith("./") else pattern
        anchor, prefix = "cwd", ("" if "/" in body else "(?:.*/)?")
    tree = body.endswith("/**")
    if tree:
        body = body[:-3]
    out, i = "", 0
    while i < len(body):
        if body.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif body.startswith("**", i):
            out, i = out + ".*", i + 2
        elif body[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif body[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(body[i]), i + 1
    return anchor, re.compile(prefix + out + ("(?:/.*)?" if tree else ""), re.IGNORECASE), dir_only


def entries(path: str = POLICY, doc: dict | None = None, settings: str | None = SETTINGS) -> list:
    """What is on the deny list, its one reader: [(entry, purpose)], the policy file's entries in order, each with
    the first purpose whose pattern matches it, then the entries that stay in settings.json (the switch's own,
    ``KEPT``; ``settings=None`` leaves them out). Raises when a file cannot be read or an entry has no purpose."""
    if doc is None:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    purposes = [(re.compile(p["match"]), p["purpose"]) for p in doc["purposes"]]
    out = [(e, next(text for rx, text in purposes if rx.search(e))) for e in doc["deny"]]
    if settings is not None:  # read and judged by the one load of a settings file, as every settings decider takes it
        from .claude_home import load_settings
        loaded, why = load_settings(settings)
        if loaded is None:
            raise (ValueError(why) if why else FileNotFoundError(f"{settings}: no such file"))
        out += [(e, KEPT) for e in loaded.get("permissions", {}).get("deny", [])]
    return out


class Policy:
    """The deny list's entries (``entries``), prepared once."""

    def __init__(self, path: str = POLICY, doc: dict | None = None, settings: str | None = SETTINGS,
                 listed: list | None = None):
        self.bash, self.skill, self.paths = [], {}, {"Read": [], "Edit": []}
        for entry, purpose in (entries(path, doc, settings) if listed is None else listed):
            m = re.fullmatch(r"(Bash|Read|Edit|Skill)\((.*)\)", entry, re.S)
            if not m:
                raise ValueError(f"deny entry of an unknown form: {entry!r}")
            tool, body = m.groups()
            if tool == "Bash":
                self.bash.append((entry, purpose) + _bash_matcher(body))
            elif tool == "Skill":
                self.skill[body] = (entry, purpose)
            else:
                lift = body.startswith("!")
                self.paths[tool].append((entry, purpose, lift) + _glob(body[1:] if lift else body))

    # ---------------------------------------------------------------- Bash command entries
    def bash_entry(self, cmd: str):
        for sub in subcommands(cmd):
            for form in match_forms(sub):
                for entry, purpose, exact, rx in self.bash:
                    if (exact is not None and form == exact) or (rx is not None and rx.fullmatch(form)):
                        return entry, purpose
        return None

    # ---------------------------------------------------------------- Read and Edit path entries
    def _list(self, tool: str, path: str, cwd: str, home: str):
        """The deciding entry of one tool's list for an absolute path, or None (last match wins)."""
        config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
        bases = [("~", home), ("src", HOME_DIR), ("src", os.path.realpath(HOME_DIR)), ("src", config), ("cwd", cwd)]
        rels = [("/", path)]
        for key, base in bases:
            base = (base or "").rstrip("/")
            if base and path.startswith(base + "/") and (key, path[len(base) + 1:]) not in rels:
                rels.append((key, path[len(base) + 1:]))
        for key, rel in rels:
            parts = rel.lstrip("/").split("/")
            lead = "/" if key == "/" else ""
            for n in range(1, len(parts) + 1):
                prefix = lead + "/".join(parts[:n])
                is_dir = n < len(parts)
                hit = None
                for entry, purpose, lift, anchor, rx, dir_only in self.paths[tool]:
                    if anchor != key or (dir_only and not is_dir):
                        continue
                    target = prefix[1:] if key == "/" else prefix
                    if rx.fullmatch(target):
                        hit = None if lift else (entry, purpose)
                if hit:
                    return hit
        return None

    def path_entry(self, path: str, write: bool, cwd: str, home: str):
        if not path:
            return None
        for lead in ("~/", "$HOME/", "${HOME}/"):
            if path.startswith(lead):
                path = os.path.join(home, path[len(lead):])
        path = os.path.normpath(os.path.join(cwd, path))
        for tool in (("Read", "Edit") if write else ("Read",)):
            hit = self._list(tool, path, cwd, home)
            if hit:
                return hit
        return None

    def _after_unknown_cd(self, word: str, write: bool):
        """A relative path read after a cd to a directory not known before the command runs: the entry whose last
        segment its name meets (the CLI's cd guard asked for every such read while it held a Read entry). A last
        segment of wildcards only (`Edit(.claude/hooks/**)`) names no file, so it decides nothing here."""
        name = word.rstrip("/").rsplit("/", 1)[-1]
        for tool in (("Read", "Edit") if write else ("Read",)):
            for entry, purpose, lift, _anchor, _rx, _dir in self.paths[tool]:
                last = entry[len(tool) + 1:-1].rstrip("/").rsplit("/", 1)[-1]
                if not lift and last.strip("*") and _glob(last)[1].fullmatch(name):
                    return entry, purpose
        return None

    def bash_paths(self, cmd: str, cwd: str, home: str):
        from .shell_parse import CWD_BUILTINS, GREP_NAMES  # GREP_NAMES: the first operand is a pattern, the rest files
        dirs, unknown = [cwd], False     # every directory a relative path may be read from: cd is followed
        for sub in subcommands(cmd):
            words = match_forms(sub)[-1].lstrip("({ ").split()
            if words and words[0] in CWD_BUILTINS:
                to = next((w.strip("'\")") for w in words[1:] if not w.startswith("-")), "~")
                to = "$" if words[0] == "popd" or "-" in words[1:] else re.sub(r"^(?:\$HOME|\$\{HOME\}|~)(?=/|$)", home, to)
                if re.search(r"[$`*?]", to):
                    unknown = True
                else:
                    dirs.append(os.path.normpath(os.path.join(dirs[-1], to)))
                continue
            found = []
            for m in OUT_TARGET.finditer(sub):
                found.append((m.group(1).strip("'\""), True))
            if words:
                prog = os.path.basename(words[0])
                operands = [w.strip("'\")") for w in words[1:] if not w.startswith("-")]
                if prog in GREP_NAMES + ("rg",):
                    operands = operands[1:]
                if prog in READERS or prog == "tee" or prog in GREP_NAMES + ("rg",):
                    found += [(w, prog == "tee") for w in operands]
            for word, write in found:
                relative = not word.startswith(("/", "~/", "$HOME/", "${HOME}/"))
                for here in (dirs if relative else dirs[:1]):
                    hit = self.path_entry(word, write, here, home)
                    if hit:
                        return hit
                if relative and unknown:
                    hit = self._after_unknown_cd(word, write)
                    if hit:
                        return hit
        return None

    # ---------------------------------------------------------------- one payload
    def refusal(self, payload: dict):
        """(tool, entry, purpose) of the entry that refuses this PreToolUse payload, or None."""
        tool = payload.get("tool_name") or ""
        ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
        home = os.path.expanduser("~")
        hit = None
        if tool == "Bash":
            cmd = str(ti.get("command") or "")
            hit = self.bash_entry(cmd) or self.bash_paths(cmd, cwd, home)
        elif tool in READ_TOOLS:
            hit = self.path_entry(str(ti.get(READ_TOOLS[tool]) or ""), False, cwd, home)
        elif tool in WRITE_TOOLS:
            hit = self.path_entry(str(ti.get(WRITE_TOOLS[tool]) or ""), True, cwd, home)
        elif tool == "Skill":
            name = str(ti.get("skill") or ti.get("name") or "").strip()
            hit = self.skill.get(name[1:] if name.startswith("/") else name)
        return (tool,) + hit if hit else None
