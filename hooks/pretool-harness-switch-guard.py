#!/usr/bin/env python3
"""PreToolUse (a rule of hooks/pretool-write-gate.py, for Bash, the file-writing tools, Skill and
SlashCommand): only the owner switches the harness.

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
                        settings*.json that would set disableAllHooks; a script that names the
                        switch's state outside the harness home and outside the session's
                        project when that is a harness checkout (_in_harness_checkout)
  every other tool      hooks/pretool-harness-switch-prompt.py's: a string of its input that types
                        /harness (the text matching of both is hooks/lib/switch_prompt.py)

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
The owner edits the file, or types /allow: the grant releases the next refused call where the
pre-tool verdicts meet (lib/hook_launch.release_refused); this guard reads no grant.

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
from claude_home import load_settings, project_dir  # noqa: E402 -- the one load of a settings file, for every decider
import shell_parse  # noqa: E402 -- the one reading of a Bash command
import bash_read_only  # noqa: E402 -- the one list of the programs that only read
import git_facts  # noqa: E402 -- what git's subcommands do to the files they name
from harness_vocabulary import WRITE_TOOLS  # noqa: E402 -- the tools that write a file
from bash_read_only import _git as _git_reads  # noqa: E402 -- the one proof that a git command only reads
from switch_prompt import TYPED, refuse  # noqa: E402 -- what types /harness, and the rule's refusal
sys.path.pop(0)

HOME = harness_switch.harness_home()
STATE_DIR = os.path.join(HOME, harness_switch.DIR_NAME)
SETTINGS_NAMES = ("settings.json", "settings.machine.json", "settings.local.json")
SWITCH_PROGRAMS = ("harness-switch", "userprompt-harness-switch.sh")
GIT_READ_ONLY = git_facts.GIT_KEEPS_NAMED_FILES  # git calls that write no file they name
# The switch's directory as a whole name (a path component or a quoted word), not inside a longer file name.
SWITCH_DIR_WORD = re.compile(r"(?<![\w.-])%s(?![\w.-])" % re.escape(harness_switch.DIR_NAME))
NESTED = re.compile(r"(?:^|[\s;|&(/])claude(?:\s|$)", re.M)  # a Claude Code session the command starts
WRITES = re.compile(r"(?<![<>&0-9])>|>>|\btee\b|\bsed\b[^|;&]*\s-i|\bdd\b|\btruncate\b")
SETTINGS_ANY = re.compile(r"settings(?:\.[\w-]+)?\.json")  # check_write's names, in any directory
NAMES_SETTINGS = re.compile(r"(?:^|[/'\"=>])" + SETTINGS_ANY.pattern + r"(?![\w-])")  # a word that names one
PROTECTED = ("env", "hooks", "disableAllHooks", "permissions")  # a settings file's keys that switch hooks
CLAUDE_SETTINGS = re.compile(r"(?:^|/)(?:\.claude/settings(?:\.local)?\.json|\.claude\.json|managed-settings\.json"
                             r"|managed-settings\.d/[^/]+\.json)\Z")  # the CLI's sources, by path
INTERPRETER = re.compile(r"(?:python[\d.]*|node|nodejs|deno|bun|ruby|perl|php|bash|sh|dash|zsh|ksh)\Z")
LITERAL_ECHO = re.compile(r"echo((?:\s+-[nE]+)*)\s+'([^']*)'\s*(>>?|>\|)\s*([\w./~+-]+)")
FALLBACK_REDIRECT = re.compile(r"(?:\d*|&)>>?\|?(.*)\Z", re.S)  # a redirection in text the parser cannot read
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OWNER_SETTINGS = ("Only the owner changes them: edit the file yourself, or type /allow, which lets the next "
                  "refused call through once")


def _resolve(path: str, cwd: str) -> str:
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))


def _in_state(path: str) -> bool:
    return path == STATE_DIR or path.startswith(STATE_DIR + os.sep)


def _settings_files() -> set:
    dirs = {HOME, os.path.realpath(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"))}
    return {os.path.join(d, n) for d in dirs for n in SETTINGS_NAMES}


def _allow_settings(cwd: str) -> bool:
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    return os.path.isfile(os.path.join(project, ".claude", ".hook-refactor-allow"))


def _in_harness_checkout(path: str) -> bool:
    """`path` (resolved) lies in the harness home, or in the session's project when that is a harness checkout:
    not in any directory an agent made to hold a file of that name."""
    project = os.path.realpath(str(project_dir()))
    roots = [HOME] + ([project] if os.path.isfile(os.path.join(project, "hooks", "lib", "harness_switch.py")) else [])
    return any(path.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def _text(word, env: dict) -> str:
    """A parsed word as text: its static parts, a $NAME `env` holds as its value, any other
    expansion as ${...} (no file name is read from what the shell computes)."""
    return "".join(p.text if p.kind in shell_parse.LITERAL_PART_KINDS else env[p.text] if p.text in env and p.kind == "param"
                   else "${%s}" % (p.text if p.kind == "param" else "") for p in word.parts)


def _commands(command: str, bodies: str, every_word: bool = False, depth: int = 0):
    """(words, written) for each simple command `command` runs, as hooks/lib/shell_parse.py reads it:
    its words as text (assignments, words, then each redirection's operator and target) and the
    paths shell_parse.write_targets says it writes. A -c or eval payload, a substitution and a
    heredoc a shell reads are commands; so is any other heredoc's body where `bodies` keeps it
    ("all"; "code": unless it feeds a commit, tag or PR message; "shell": none). With `every_word`
    a word holding a space or ; | & is read as commands too. A $NAME is read from the call's
    environment or an assignment before it; text the parser cannot read is split on whitespace,
    a word after a redirection operator, or attached to one, written."""
    script, env, message, targets = shell_parse.parse(command), dict(os.environ), [], {}
    for t in shell_parse.write_targets(script):
        targets.setdefault((t.context, t.word.span), []).append(t.word)
    for site in shell_parse.walk(script):
        cmd, level = site.cmd, len(site.context)
        while message and message[-1] >= level:
            message.pop()
        for a in cmd.assignments if not cmd.words else ():
            env.pop(a.name, None) if a.static_value() is None else env.update({a.name: a.static_value()})
        words = [_text(w, env) for w in [a.word for a in cmd.assignments] + list(cmd.words)]
        spans = {w.span for w in cmd.words} | {r.target.span for r in cmd.redirects if r.target is not None}
        written = [_text(w, env) for span in spans for w in targets.pop((site.context, span), ())]
        for r in cmd.redirects:
            words += [(r.io or "") + r.op, _text(r.target, env)] if r.target is not None else []
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if plain and _message(plain):
            message.append(level)
        yield words, written
        for w in words if every_word and depth < 3 else ():
            if any(c in w for c in " ;|&\n"):
                yield from _commands(w, bodies, every_word, depth + 1)
        shell = shell_parse.resolve(cmd).payload_kind == "heredoc_shell"
        for r in cmd.redirects if bodies == "all" or (bodies == "code" and not message) else ():
            if r.hd is not None and not shell and depth < 3:
                yield from _commands(r.hd.body, bodies, every_word, depth + 1)
    for word in [w for ws in targets.values() for w in ws]:  # a redirection of a compound command
        yield [">", _text(word, env)], [_text(word, env)]
    for line in command.splitlines() if script.error is not None else ():
        words = line.split()
        yield words, [m.group(1) or nxt for w, nxt in zip(words, words[1:] + [""]) for m in [FALLBACK_REDIRECT.match(w)] if m]


REDIRECT_OP = re.compile(r"(?:\d*|&|\{\w+\})[<>][<>&|-]*\Z")  # an operator _commands appends with its target


def _read_only(words: list) -> bool:
    """The command writes no file a word of it names: a reader of hooks/lib/bash_read_only.py
    (its pagers included) whose arguments pass that program's check, or a reading git call."""
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]  # the command's prefix assignments (`-c a=b` keeps its value word)
    if not words:
        return True
    head = os.path.basename(words[0])
    if head == "git":
        k = shell_parse.git_subcommand_index(words[1:])
        sub = "" if k is None else words[1 + k]
        return (sub in GIT_READ_ONLY or _git_reads(words[1:])) and "-delete" not in words
    args, it = [], iter(words[1:])
    for w in it:
        if REDIRECT_OP.match(w):
            next(it, None)  # a redirection's target is a written path of its own (write_targets)
        else:
            args.append(w)
    return bash_read_only.reads_only(head, args, pagers=True)


def _written_words(words: list, written: list, everything=None) -> list:
    """The words of one simple command that name what it writes: the paths it writes, and, for a
    command that is not read-only (cp, mv, tee, sed -i, python, ...), every word (`everything`
    False: the paths alone). The command is judged at its command word as hooks/lib/shell_parse.py
    resolves it: of a reader behind wrappers (command, timeout, env ...) only the wrappers' words."""
    own = plain = [w for w in words if not ASSIGNMENT.match(w)]
    if everything is None:
        cmd = next(shell_parse.iter_commands(shell_parse.parse(shlex.join(plain)), into=()), None)
        head = shell_parse.resolve(cmd).head
        own = plain[cmd.words.index(head):] if cmd is not None and head in cmd.words else plain
        everything = bool(own) and not _read_only(own)
    if everything and os.path.basename(own[0]) == "sed":
        everything = any(re.fullmatch(r"-[A-Za-z]*i.*|--in-place.*", w) for w in own[1:])
    return written + (words if everything else plain[:len(plain) - len(own)])


def writes_settings_file(command: str) -> bool:
    """True when `command` writes a settings*.json file, in any directory."""
    return any(NAMES_SETTINGS.search(w) for words, written in _commands(command, "code")
               for w in _written_words(words, written))


def _may_name_settings(token: str) -> bool:
    """Whether `token` can name a settings file or a directory holding one by its spelling alone,
    wherever it is read from: its last component as written is a .json name, .claude,
    managed-settings.d, or `.`, `..` or nothing, which only the directory it is read from resolves.
    Any other word names one only when its real path's last component does (_named_settings)."""
    last = os.path.basename(token.rstrip("/"))
    return last in ("", ".", "..", ".claude", "managed-settings.d") or last.endswith(".json")


def _named_settings(word: str, dirs: list, dirs_too=False, home=None) -> list:
    """The Claude Code settings files `word` names, read from each directory in `dirs`, as written
    and with links resolved; with `dirs_too` (None: when no directory is there now) also a
    directory holding them. The home's own settings files are the rule above's, not these.
    Each path is resolved once (os.path.realpath), and a word whose spelling names none
    (_may_name_settings) is judged further only where its real path's name can, so a padded
    command stays cheap. The rule decides on names, as written and resolved, and tests no file
    itself: an os.path.islink of a word would make it a decider on every file a word can name,
    the subagent meta.json the write gate's other rules decide on included (the artifact
    check's rule (4))."""
    out, home = [], _settings_files() if home is None else home
    for token in {word, word.split("=", 1)[-1]}:
        token = os.path.expanduser(token)
        spelled = _may_name_settings(token)
        for d in dirs:
            lexical = os.path.normpath(os.path.join(d, token))
            real = os.path.realpath(lexical)
            if not spelled and not _may_name_settings(real):
                continue  # neither its name as written nor its real path's is a settings name
            for p, p_real in ((lexical, real), (real, os.path.realpath(real))):
                if p_real not in home and (CLAUDE_SETTINGS.search(p) or _settings_dir(p, dirs_too)):
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
        head == "gh" and sub in git_facts.GH_MESSAGE_SUBCOMMANDS)


def _operands(plain: list, moves: bool) -> list:
    """cp / mv: (word, dirs_too) for the destination, each source's name inside it, and, for mv,
    each source (moved away); cp's sources are only read."""
    sources, dest, it = [], None, iter(plain[1:])
    for w in it:
        if w in shell_parse.TARGET_DIR_OPTS:
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
    destination, and mv's sources. A path is read from the call's directory and every `cd`'s.
    Each directory, and each word with its kind, is read once: a command padded with repeated
    `cd .` costs what its distinct words cost, not their count times its segments'."""
    segments = list(_commands(command, "shell"))
    cds = dict.fromkeys(w[1] for w, _ in segments if len(w) > 1 and os.path.basename(w[0]) in shell_parse.CD_TARGET_BUILTINS)
    dirs = list(dict.fromkeys([cwd] + [_resolve(w, cwd) for w in cds]))
    out, seen, home = [], set(), _settings_files()
    for words, written in segments:
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if not plain:
            continue
        head = os.path.basename(plain[0])
        interpreter = INTERPRETER.match(head) and not any(re.fullmatch(r"-[A-Za-z]*i.*", w) for w in plain[1:])
        message, moves = _message(plain), head in shell_parse.CP_MV
        named = [(w, head in ("rm", "rmdir", "rsync")) for w in
                 _written_words(words, written, False if (interpreter or message or moves) else None)]
        named += _operands(plain, head == "mv") if moves else []
        for word, dirs_too in named:
            if (word, dirs_too) not in seen:
                seen.add((word, dirs_too))
                out.extend(_named_settings(word, dirs, dirs_too, home))
    return list(dict.fromkeys(out))


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
    for words, _ in _commands(command, "all", every_word=True):
        writes = bool(WRITES.search(" ".join(words))) or not _read_only(words)
        for word in words:
            token = word.split("=", 1)[-1]
            if os.path.basename(token.rstrip("/")) in SWITCH_PROGRAMS and not _read_only(words):
                return refuse("this Bash command runs the switch (%s)" % os.path.basename(token))
            if SWITCH_DIR_WORD.search(token) and writes:
                return refuse("this Bash command changes the switch's state (%s)" % harness_switch.DIR_NAME)
            if os.path.basename(token) in SETTINGS_NAMES and writes and not _allow_settings(cwd):
                if _resolve(token, cwd) in settings:
                    return refuse("this Bash command writes the harness home's %s" % os.path.basename(token))
    for path in settings_writes(command, cwd):
        before = _current(path)
        change = _settings_change(_held(path), _echo_result(command, path, cwd, before))
        if change:
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
        if change:
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
    if tool in WRITE_TOOLS:
        return check_write(tool, ti, cwd, data)
    if tool in ("Skill", "SlashCommand"):
        return check_skill(tool, ti)
    return 0  # every other tool is hooks/pretool-harness-switch-prompt.py's


if __name__ == "__main__":
    sys.exit(main())
