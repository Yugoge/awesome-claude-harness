#!/usr/bin/env python3
"""PreToolUse (a rule of hooks/pretool-write-gate.py, every tool): only the owner switches the harness.

The owner's typed /harness off|on reaches hooks/userprompt-harness-switch.sh, a UserPromptSubmit
hook: the one event an agent cannot produce. This rule refuses, for the main agent and every
subagent, each other path by which an agent call could switch the harness or fake a switch:

  Skill / SlashCommand  invoking the harness command (its settings deny and its
                        disable-model-invocation say the same)
  Bash                  running scripts/harness-switch or the switch hook; touching the switch's
                        state <H>/.harness-switch/ other than reading it; typing `/harness on|off`
                        into a Claude Code session the command starts; writing the home's
                        settings files (settings.json, settings.machine.json, settings.local.json);
                        writing disableAllHooks into any settings*.json, in any project
  Write / Edit / MultiEdit / NotebookEdit
                        a file under <H>/.harness-switch/; the home's settings files; any
                        settings*.json that would set disableAllHooks; a script outside a harness
                        checkout that names the switch's state
  CronCreate / ScheduleWakeup / SendMessage
                        a prompt or message that types /harness (a scheduled prompt reaches
                        UserPromptSubmit as if typed)

A Claude Code settings file's env, hooks, disableAllHooks and permissions decide which hooks run,
with what environment, and what is asked (an env value reaches every hook), so they are the
owner's too, by key, whatever variable an env names. A settings file is what the CLI loads one
from: .claude/settings.json and .claude/settings.local.json in any directory, managed-settings.json
and a managed-settings.d/*.json, and .claude.json (the global config, whose env the CLI applies at
launch); a --settings file can be anywhere and is not seen. The home's own settings files stay
the rule above's.
  Write / Edit / MultiEdit
                        refused when one of those keys' value in the document the call leaves
                        differs from the file's now (added, changed or removed; the file read
                        by hooks/lib/claude_home.py's load_settings, an unusable one refused), or
                        the document cannot be computed, or is no JSON object while the file holds
                        one of them
  NotebookEdit          refused on a settings file (no notebook, its result is not computed)
  Bash                  refused when a command writes, moves or removes a settings file (a
                        redirect, tee, cp or mv onto it, sed -i, rm, mv away, any command but a
                        reader, an interpreter or a commit or PR message naming it; a heredoc
                        body is commands only where a shell reads it), unless the whole command
                        is `echo '<literal>' > or >> <file>` whose result the Write rule passes;
                        an interpreter's own writes are not seen
The owner edits the file, or grants the one call with /allow (hooks/lib/allowlist.py; spent after
the call by hooks/posttool-allowlist-consume.py): a Bash grant naming the command, for any actor,
as every Bash grant is; `/allow Write <path>`, or `/allow <tool>`, for the main agent, as the
overwrite rule's Write grant is.

Reading stays free (status: scripts/harness-switch status is the owner's, through /harness
status). The home's settings files stay writable for a /dev cycle on the harness only where the
project holds the hand-made .claude/.hook-refactor-allow sentinel. While the harness is off this
rule does not run either (the switch is the owner's then, as everything else is).
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib")); import harness_switch; sys.path.pop(0)  # noqa: E402,E702
harness_switch.exit_if_off()

import json  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
from claude_home import load_settings  # noqa: E402 -- the one load of a settings file, for every decider
sys.path.pop(0)

HOME = harness_switch.harness_home()
STATE_DIR = os.path.join(HOME, harness_switch.DIR_NAME)
SETTINGS_NAMES = ("settings.json", "settings.machine.json", "settings.local.json")
SWITCH_PROGRAMS = ("harness-switch", "userprompt-harness-switch.sh")
READ_ONLY = {"cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "wc", "ls", "stat",
             "file", "jq", "diff", "cmp", "md5sum", "sha256sum", "test", "[", "echo", "printf", "realpath",
             "readlink", "basename", "dirname", "find"}
GIT_READ_ONLY = {"add", "diff", "log", "show", "status", "blame", "ls-files", "check-attr", "cat-file",
                 "grep", "rev-parse", "stash"}
NESTED = re.compile(r"(?:^|[\s;|&(/])claude(?:\s|$)", re.M)  # a Claude Code session the command starts
TYPED = re.compile(r"(?:^|[\s\"'`(])/harness(?:\s+(?:on|off|status)\b|\s*$|[\s\"'`)])", re.M)
WRITES = re.compile(r"(?<![<>&0-9])>|>>|\btee\b|\bsed\b[^|;&]*\s-i|\bdd\b|\btruncate\b")
SETTINGS_ANY = re.compile(r"settings(?:\.[\w-]+)?\.json")  # check_write's names, in any directory
NAMES_SETTINGS = re.compile(r"(?:^|[/'\"=>])" + SETTINGS_ANY.pattern + r"(?![\w-])")  # a word that names one
REDIRECT = re.compile(r"^(?:\d*|&)>>?\|?(.*)\Z", re.S)
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")
MESSAGE = re.compile(r"\bgit\b[^\n]*\b(?:commit|tag|notes|merge|revert)\b|\bgh\b[^\n]*\b(?:pr|issue|release)\b")
PROTECTED = ("env", "hooks", "disableAllHooks", "permissions")  # a settings file's keys that switch hooks
CLAUDE_SETTINGS = re.compile(r"(?:^|/)(?:\.claude/settings(?:\.local)?\.json|\.claude\.json|managed-settings\.json"
                             r"|managed-settings\.d/[^/]+\.json)\Z")  # the CLI's sources, by path
INTERPRETER = re.compile(r"(?:python[\d.]*|node|nodejs|deno|bun|ruby|perl|php|bash|sh|dash|zsh|ksh)\Z")
LITERAL_ECHO = re.compile(r"echo((?:\s+-[nE]+)*)\s+'([^']*)'\s*(>>?|>\|)\s*([\w./~+-]+)")
SHELL_FED = re.compile(r"(?:^|[\s;|&(/])(?:bash|sh|dash|zsh|ksh)(?:\s|<|$)")  # a shell reads the heredoc
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OWNER_SWITCHES = ("Only the owner switches the harness, by typing /harness off or /harness on; nothing an "
                  "agent runs, writes or schedules does")
OWNER_SETTINGS = ("Only the owner changes them: edit the file yourself, or type /allow for this one call "
                  "(/allow <the command> for Bash; /allow Write <path>, or /allow <tool> for Edit, MultiEdit "
                  "or NotebookEdit, for the main agent's call)")


def refuse(what: str, owner: str = OWNER_SWITCHES) -> int:
    sys.stderr.write("BLOCKED: harness-switch: %s. %s.\n" % (what, owner))
    return 2


def _resolve(path: str, cwd: str) -> str:
    path = os.path.expanduser(os.path.expandvars(path))
    return os.path.realpath(os.path.join(cwd, path))


def _in_state(path: str) -> bool:
    return path == STATE_DIR or path.startswith(STATE_DIR + os.sep)


def _settings_files() -> set:
    dirs = {HOME, os.path.realpath(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"))}
    return {os.path.join(d, n) for d in dirs for n in SETTINGS_NAMES}


def _allow_settings(cwd: str) -> bool:
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    return os.path.isfile(os.path.join(project, ".claude", ".hook-refactor-allow"))


def _in_harness_checkout(path: str) -> bool:
    d = os.path.dirname(path)
    while True:
        if os.path.isfile(os.path.join(d, "hooks", "lib", "harness_switch.py")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _is_shell_text(words: list, i: int) -> bool:
    """True when words[i] is shell text a command runs: bash -c "...", eval "..."."""
    return i > 0 and (os.path.basename(words[0]) == "eval" or bool(re.fullmatch(r"-[A-Za-z]*c", words[i - 1])))


def _segments(command: str, depth: int = 0, shell_text_only: bool = False) -> list:
    """The simple commands of `command` as word lists, quotes respected; a word that is itself a
    command (bash -c "...", sh -c, eval) is read as its own commands too. With `shell_text_only`
    only those words are: a commit message with spaces is prose, not commands."""
    out = []
    for line in command.splitlines() or [""]:
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lex.whitespace_split = True
            tokens = list(lex)
        except ValueError:
            tokens = line.split()
        current = []
        for token in tokens:
            if token and set(token) <= set(";&|"):
                if current:
                    out.append(current)
                current = []
            else:
                current.append(token)
        if current:
            out.append(current)
    if depth < 3:
        for words in list(out):
            for i, word in enumerate(words):
                if any(c in word for c in " ;|&\n") and (not shell_text_only or _is_shell_text(words, i)):
                    out.extend(_segments(word, depth + 1, shell_text_only))
    return out


def _read_only(words: list) -> bool:
    words = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
    if not words:
        return True
    head = os.path.basename(words[0])
    if head == "git":
        sub = next((w for w in words[1:] if not w.startswith("-")), "")
        return sub in GIT_READ_ONLY and "-delete" not in words
    return head in READ_ONLY and "-delete" not in words and "-exec" not in words


def _without_message_bodies(command: str, data_too: bool = False) -> str:
    """`command` minus the bodies of heredocs that feed a commit, tag or PR message: prose, not
    code. Every other heredoc body stays: a script a command writes, or an interpreter reads.
    With `data_too` only a body a shell reads stays (its lines are commands; any other is data)."""
    out, end, keep = [], None, True
    for line in command.splitlines():
        if end is not None:
            if line.strip() == end:
                end = None
            elif keep:
                out.append(line)
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end, keep = m.group(2), bool(SHELL_FED.search(line)) if data_too else not MESSAGE.search(line)
    return "\n".join(out)


def _written_words(words: list, everything=None) -> list:
    """The words of one simple command that name what it writes: the targets of its redirections,
    and, for a command that is not read-only (cp, mv, tee, sed -i, python, ...), every word
    (`everything` False: the redirections' targets alone)."""
    plain = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
    if everything is None:
        everything = bool(plain) and not _read_only(plain)
    if everything and os.path.basename(plain[0]) == "sed":
        everything = any(re.fullmatch(r"-[A-Za-z]*i.*|--in-place.*", w) for w in plain[1:])
    named, after = [], False
    for w in words:
        m = REDIRECT.match(w)
        if after:
            named.append(w)
            after = False
        elif m:
            if m.group(1):
                named.append(m.group(1))
            else:
                after = True
        elif everything:
            named.append(w)
    return named


def writes_settings_file(command: str) -> bool:
    """True when `command` writes a settings*.json file, in any directory."""
    for words in _segments(_without_message_bodies(command), shell_text_only=True):
        if any(NAMES_SETTINGS.search(w) for w in _written_words(words)):
            return True
    return False


def _named_settings(word: str, dirs: list, dirs_too=False) -> list:
    """The Claude Code settings files `word` names, read from each directory in `dirs`, as written
    and with links resolved; with `dirs_too` (None: when no directory is there now) also a
    directory holding them. The home's own settings files are the rule above's, not these."""
    out, home = [], _settings_files()
    for token in {word, word.split("=", 1)[-1]}:
        for d in dirs:
            lexical = os.path.normpath(os.path.join(d, os.path.expanduser(os.path.expandvars(token))))
            for p in (lexical, os.path.realpath(lexical)):
                if os.path.realpath(p) not in home and (CLAUDE_SETTINGS.search(p) or _settings_dir(p, dirs_too)):
                    out.append(p)
    return out


def _settings_dir(path: str, dirs_too) -> bool:
    """`path` is a .claude or managed-settings.d directory a command removes or replaces."""
    head, name = os.path.split(path)
    if name == ".claude":
        return bool(dirs_too) or (dirs_too is None and not os.path.isdir(os.path.join(head, ".claude")))
    if name == "managed-settings.d":
        return bool(dirs_too) or (dirs_too is None and not os.path.isdir(os.path.join(head, "managed-settings.d")))
    return False


def _message(plain: list) -> bool:
    """A commit, tag or PR command: its words are a message, prose that may name a path."""
    head, sub = os.path.basename(plain[0]), next((w for w in plain[1:] if not w.startswith("-")), "")
    return (head == "git" and sub in ("commit", "tag", "notes", "merge", "revert")) or (
        head == "gh" and sub in ("pr", "issue", "release"))


def _operands(plain: list, moves: bool) -> list:
    """cp / mv: (word, dirs_too) for the destination, each source's name inside it, and, for mv,
    each source (moved away); cp's sources are only read."""
    sources, dest, it = [], None, iter(plain[1:])
    for w in it:
        if w in ("-t", "--target-directory"):
            dest = next(it, None)
        elif w.startswith("--target-directory="):
            dest = w.split("=", 1)[1]
        elif not w.startswith("-"):
            sources.append(w)
    if dest is None and sources:
        dest = sources.pop()
    if dest is None:
        return []
    inside = [(os.path.join(dest, os.path.basename(s.rstrip("/"))), True) for s in sources]
    return [(dest, None)] + inside + ([(s, True) for s in sources] if moves else [])


def settings_writes(command: str, cwd: str) -> list:
    """The Claude Code settings files (and directories holding them) `command` writes, moves or
    removes: a redirect onto one (spaced or attached), and every word of a command that is not a
    reader, an interpreter or a commit or PR message (tee, sed -i, rm, ...); cp's and mv's
    destination, and mv's sources. A path is read from the call's directory and every `cd`'s."""
    segments = _segments(_without_message_bodies(command, data_too=True), shell_text_only=True)
    dirs = [cwd] + [_resolve(w[1], cwd) for w in segments if len(w) > 1 and os.path.basename(w[0]) in ("cd", "pushd")]
    out = []
    for words in segments:
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if not plain:
            continue
        head = os.path.basename(plain[0])
        interpreter = INTERPRETER.match(head) and not any(re.fullmatch(r"-[A-Za-z]*i.*", w) for w in plain[1:])
        message, moves = _message(plain), head in ("cp", "mv")
        named = [(w, head in ("rm", "rmdir", "rsync")) for w in
                 _written_words(words, False if (interpreter or message or moves) else None)]
        named += _operands(plain, head == "mv") if moves else []
        named += [] if message else [(w.rsplit(">", 1)[1].lstrip("|"), False) for w in words
                                     if ">" in w and not REDIRECT.match(w)]
        for word, dirs_too in named:
            out.extend(_named_settings(word, dirs, dirs_too))
    return out


def _settings_path(path: str):
    """`path` spelled by its settings kind's own name; None for a directory or any other file."""
    head, name = os.path.split(path)
    parent, folder = os.path.split(head)
    if folder == ".claude" and name == "settings.json":
        return os.path.join(parent, ".claude", "settings.json")
    if folder == ".claude" and name == "settings.local.json":
        return os.path.join(parent, ".claude", "settings.local.json")
    if name == ".claude.json":
        return os.path.join(head, ".claude.json")
    if name == "managed-settings.json":
        return os.path.join(head, "managed-settings.json")
    if folder == "managed-settings.d" and name.endswith(".json"):
        return os.path.join(parent, "managed-settings.d", name)
    return None


def _held(path: str):
    """{key: canonical value} of the protected keys the file holds now ({} when there is none);
    None when hooks/lib/claude_home.py's load finds it unusable, or `path` is no settings file."""
    p = _settings_path(path)
    settings, problem = load_settings(p) if p else (None, "no settings file")
    if problem:
        return None
    return {k: json.dumps(settings[k], sort_keys=True) for k in PROTECTED if k in (settings or {})}


def _current(path: str):
    """The file's text, for an edit to apply to (None: there is none; False: it cannot be read)."""
    p = _settings_path(path)
    if p is None:
        return False
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, UnicodeDecodeError):
        return False


def _no_constant(name):
    raise ValueError(name)  # NaN, Infinity: JSON.parse refuses them, so the CLI loads no such file


def _protected(text: str):
    """{key: canonical value} of the protected keys a settings document holds; None when the CLI
    would load no document from it (not JSON, or not an object)."""
    try:
        doc = json.loads(text.lstrip("﻿"), parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(doc, dict):
        return None
    return {k: json.dumps(doc[k], sort_keys=True) for k in PROTECTED if k in doc}


def _settings_change(old, after) -> str:
    """What a call does to the protected keys, as a verb phrase; "" when it leaves them as they are.
    `old`: the keys the file holds now (_held; None: unusable); `after`: the text the call leaves
    (None: not computed)."""
    if old is None or after is None:
        return "may change env, hooks, disableAllHooks or permissions in"
    new = _protected(after)
    if new is None:
        return "drops %s from" % ", ".join(old) if old else ""
    keys = [k for k in PROTECTED if old.get(k) != new.get(k)]
    return "changes %s in" % ", ".join(keys) if keys else ""


def _echo_result(command: str, path: str, cwd: str, before):
    """The text `echo '<literal>' > or >> <file>`, the whole command, leaves in `path`; None for
    any other command (the shell decides its result: what it reads, expands or runs)."""
    m = LITERAL_ECHO.fullmatch(command.strip())
    if not m or before is False or _resolve(m.group(4), cwd) != os.path.realpath(path):
        return None
    text = m.group(2) + ("" if "n" in m.group(1) else "\n")
    return (before or "") + text if m.group(3) == ">>" else text


def _edit_result(tool: str, ti: dict, before):
    """The text a Write, Edit or MultiEdit leaves in the file; None when it is not computed here
    (a NotebookEdit, an old_string the file does not hold, an unreadable file)."""
    if tool == "Write":
        return str(ti.get("content") or "")
    edits = [ti] if tool == "Edit" else ti.get("edits") if tool == "MultiEdit" else None
    if before is False or not isinstance(edits, list):
        return None
    text = before
    for e in edits:
        old, new = (e.get("old_string"), e.get("new_string")) if isinstance(e, dict) else (None, None)
        if not isinstance(old, str) or not isinstance(new, str) or (old and (text is None or old not in text)):
            return None
        if not old:
            if text:
                return None  # an empty old_string fills only a file that is missing or empty
            text = new
        else:
            text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def _granted(tool: str, ti: dict, data: dict) -> bool:
    """The owner's /allow grant for this one call (hooks/lib/allowlist.py), as each grant already
    reaches: a Bash grant naming the command, for the main agent and subagents alike; for the main
    agent alone, `/allow Write <path>` (or bare `/allow Write`) and `/allow <tool>`.
    hooks/posttool-allowlist-consume.py spends it once the call ends."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    try:
        from lib.allowlist import (match_sentinel_grant_for_bash_command, match_sentinel_grant_for_tool,
                                   match_sentinel_grant_for_write)
        sid = str(data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "default")
        key = os.environ.get("CLAUDE_TASK_ID") or sid
        if tool == "Bash":
            return match_sentinel_grant_for_bash_command(key, str(ti.get("command") or "")) is not None
        if data.get("agent_id"):
            return False
        if tool == "Write" and match_sentinel_grant_for_write(key, sid, str(ti.get("file_path") or "")):
            return True
        return match_sentinel_grant_for_tool(sid, tool) is not None
    except Exception:
        return False
    finally:
        sys.path.pop(0)


def _refuse_settings(tool: str, change: str, path: str) -> int:
    return refuse("this %s %s %s, a Claude Code settings file: its env, hooks, disableAllHooks and permissions "
                  "decide which hooks run, with what environment, and what is asked" % (tool, change, path),
                  OWNER_SETTINGS)


def check_bash(command: str, cwd: str, data: dict | None = None) -> int:
    if "disableAllHooks" in command and writes_settings_file(command):
        return refuse("this Bash command writes disableAllHooks into a settings file, which would switch every "
                      "hook off")
    if TYPED.search(command) and NESTED.search(command):
        return refuse("this Bash command types /harness into a Claude Code session, where it would reach "
                      "the switch as a prompt")
    settings = _settings_files()
    for words in _segments(command):
        writes = bool(WRITES.search(" ".join(words))) or not _read_only(words)
        for word in words:
            token = word.split("=", 1)[-1]
            if os.path.basename(token.rstrip("/")) in SWITCH_PROGRAMS and not _read_only(words):
                return refuse("this Bash command runs the switch (%s)" % os.path.basename(token))
            if harness_switch.DIR_NAME in token and writes:
                return refuse("this Bash command changes the switch's state (%s)" % harness_switch.DIR_NAME)
            if os.path.basename(token) in SETTINGS_NAMES and writes and not _allow_settings(cwd):
                if _resolve(token, cwd) in settings:
                    return refuse("this Bash command writes the harness home's %s" % os.path.basename(token))
    for path in settings_writes(command, cwd):
        before = _current(path)
        change = _settings_change(_held(path), _echo_result(command, path, cwd, before))
        if change and not _granted("Bash", {"command": command}, data or {}):
            return _refuse_settings("Bash command", change, path)
    return 0


def _new_text(tool: str, ti: dict) -> str:
    if tool == "Write":
        return str(ti.get("content") or "")
    if tool == "Edit":
        return str(ti.get("new_string") or "")
    if tool == "MultiEdit":
        return "\n".join(str(e.get("new_string") or "") for e in ti.get("edits") or [] if isinstance(e, dict))
    return str(ti.get("new_source") or "")


def check_write(tool: str, ti: dict, cwd: str, data: dict | None = None) -> int:
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    if not isinstance(raw, str) or not raw:
        return 0
    path = _resolve(raw, cwd)
    if _in_state(path):
        return refuse("this %s writes the switch's state (%s)" % (tool, raw))
    text = _new_text(tool, ti)
    name = os.path.basename(path)
    if SETTINGS_ANY.fullmatch(name) and "disableAllHooks" in text:
        return refuse("this %s sets disableAllHooks in %s, which would switch every hook off" % (tool, raw))
    if path in _settings_files() and not _allow_settings(cwd):
        return refuse("this %s writes the harness home's %s" % (tool, name))
    named = _named_settings(raw, [cwd])
    if named:
        before = _current(named[0])
        change = _settings_change(_held(named[0]), _edit_result(tool, ti, before))
        if change and not _granted(tool, ti, data or {}):
            return _refuse_settings(tool, change, raw)
    if harness_switch.DIR_NAME in text and not _in_harness_checkout(path):
        return refuse("this %s writes a file naming the switch's state (%s), outside the harness" % (tool, raw))
    return 0


def check_skill(tool: str, ti: dict) -> int:
    name = str(ti.get("skill") or ti.get("command") or ti.get("name") or "").strip().lstrip("/")
    stem = name.split()[0] if name else ""
    if stem == "harness" or stem.endswith(":harness"):
        return refuse("this %s call invokes /harness" % tool)
    return 0


def check_prompt(tool: str, ti: dict) -> int:
    for key in ("prompt", "message", "content"):
        value = ti.get(key)
        if isinstance(value, str) and TYPED.search(value):
            return refuse("this %s carries a prompt that types /harness" % tool)
    return 0


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) and data.get("cwd") else os.getcwd()
    if tool == "Bash":
        return check_bash(str(ti.get("command") or ""), cwd, data)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return check_write(tool, ti, cwd, data)
    if tool in ("Skill", "SlashCommand"):
        return check_skill(tool, ti)
    if tool in ("CronCreate", "ScheduleWakeup", "SendMessage"):
        return check_prompt(tool, ti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
