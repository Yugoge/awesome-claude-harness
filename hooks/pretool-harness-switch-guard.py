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


def refuse(what: str) -> int:
    sys.stderr.write("BLOCKED: harness-switch: %s. Only the owner switches the harness, by typing "
                     "/harness off or /harness on; nothing an agent runs, writes or schedules does.\n" % what)
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


def _without_message_bodies(command: str) -> str:
    """`command` minus the bodies of heredocs that feed a commit, tag or PR message: prose, not
    code. Every other heredoc body stays: a script a command writes, or an interpreter reads."""
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
            end, keep = m.group(2), not MESSAGE.search(line)
    return "\n".join(out)


def _written_words(words: list) -> list:
    """The words of one simple command that name what it writes: the targets of its redirections,
    and, for a command that is not read-only (cp, mv, tee, sed -i, python, ...), every word."""
    plain = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
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


def check_bash(command: str, cwd: str) -> int:
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
    return 0


def _new_text(tool: str, ti: dict) -> str:
    if tool == "Write":
        return str(ti.get("content") or "")
    if tool == "Edit":
        return str(ti.get("new_string") or "")
    if tool == "MultiEdit":
        return "\n".join(str(e.get("new_string") or "") for e in ti.get("edits") or [] if isinstance(e, dict))
    return str(ti.get("new_source") or "")


def check_write(tool: str, ti: dict, cwd: str) -> int:
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
        return check_bash(str(ti.get("command") or ""), cwd)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return check_write(tool, ti, cwd)
    if tool in ("Skill", "SlashCommand"):
        return check_skill(tool, ti)
    if tool in ("CronCreate", "ScheduleWakeup", "SendMessage"):
        return check_prompt(tool, ti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
