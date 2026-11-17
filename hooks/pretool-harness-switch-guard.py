#!/usr/bin/env python3
"""PreToolUse (a rule of hooks/pretool-write-gate.py, every tool): only the owner switches the harness.

The owner's typed /harness off|on reaches hooks/userprompt-harness-switch.sh, a UserPromptSubmit
hook: the one event an agent cannot produce. This rule refuses, for the main agent and every
subagent, each other path by which an agent call could switch the harness or fake a switch:

  Skill / SlashCommand  invoking the harness command (its settings deny and its
                        disable-model-invocation say the same)
  Bash                  running scripts/harness-switch or the switch hook; writing the switch's
                        state <H>/.harness-switch/ (a word the command writes, read from the call's
                        directory and every `cd`'s, as below; reading it is free); typing `/harness on|off`
                        into a Claude Code session the command starts; writing the home's
                        settings files (settings.json, settings.machine.json, settings.local.json);
                        writing disableAllHooks into any settings*.json, in any project. A command
                        writes only the words it writes (_written_by: a redirect's target, cp's
                        destination, sed's w file, every word of any command but a reader), never
                        a `>` elsewhere: `grep x ~/.claude/settings.json > /tmp/out` reads
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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
from claude_home import load_settings  # noqa: E402 -- the one load of a settings file, for every decider
import shell_parse  # noqa: E402 -- the one reading of a Bash command
sys.path.pop(0)

HOME = harness_switch.harness_home()
STATE_DIR = os.path.join(HOME, harness_switch.DIR_NAME)
SETTINGS_NAMES = ("settings.json", "settings.machine.json", "settings.local.json")
SWITCH_PROGRAMS = ("harness-switch", "userprompt-harness-switch.sh")
READ_ONLY = {"cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "wc", "ls", "stat",
             "file", "jq", "diff", "cmp", "md5sum", "sha256sum", "test", "[", "echo", "printf", "realpath",
             "readlink", "basename", "dirname", "find", "nl", "cut", "tr", "column", "od"}  # no output operand
READER_OUTPUT = {  # a reader's options that write a file or run a program: it is no reader with one
    "find": re.compile(r"-(?:delete|exec|execdir|ok|okdir|fprint|fprint0|fprintf|fls)\Z"),
    "less": re.compile(r"-[A-Za-z]*[oO]|--(?:log-file|LOG-FILE)(?:=|\Z)"),
    "more": re.compile(r"\A\Z"),
    "rg": re.compile(r"--pre(?:=|\Z)")}
AWKS = ("awk", "gawk", "mawk", "nawk")
AWK_OUTPUT = re.compile(r"[>|]|\bsystem\b")  # print > file, print | command, system(): an awk program that writes
AWK_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
SED_FLAGS = set("nErsuzb")  # sed's short options that take no value and write nothing
SED_LONG = ("--quiet", "--silent", "--regexp-extended", "--separate", "--unbuffered", "--null-data", "--posix",
            "--debug", "--sandbox", "--follow-symlinks", "--binary")
WRITE_SIGN = re.compile(  # an interpreter's -c / -e text that may write a file or run a program
    r"write|dump|replace|rename|copy|move|unlink|remove|rmtree|truncate|chmod|chown|link|mkdir|touch|system"
    r"|popen|subprocess|spawn|exec|eval|shutil|pathlib|Path|import\s+os|from\s+os|\bos\.|fs\.|child_process"
    r"|[>`|]|\$\(|[\"'][rwaxbt+]*[wax][rwaxbt+]*[\"']")
GIT_READ_ONLY = {"add", "diff", "log", "show", "status", "blame", "ls-files", "check-attr", "cat-file",
                 "grep", "rev-parse", "stash"}
GIT_WRAPPERS = ("env", "command", "exec", "nohup", "setsid", "nice", "ionice", "stdbuf", "timeout", "time")
GIT_EQ_OPTS = shell_parse.GIT_GLOBAL_VALUE_OPTS | {"--exec-path", "--list-cmds"}  # git's options that take =value
GIT_PROGRAM_KEY = re.compile(  # a config key whose value names a program git runs, or more config
    r"(?i)(?:alias|pager|filter|credential|include|includeif|man|browser|difftool|mergetool|gpg|sendemail"
    r"|uploadpack|receivepack|remote|url|protocol)\.|core\.(?:hookspath|fsmonitor|sshcommand|pager|editor"
    r"|askpass|gitproxy|alternaterefscommand)\Z|(?:diff|merge)\.(?:.+\.)?(?:external|textconv|command|driver"
    r"|tool)\Z|(?:sequence|interactive)\.|ssh\.|uploadarchive\.|instaweb\.|web\.")
GIT_CONFIG_ENV = r"(?:GIT_CONFIG_(?:PARAMETERS|COUNT|KEY_\d+|VALUE_\d+|GLOBAL|SYSTEM)?|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH)="
GIT_RUNS_OR_WRITES = re.compile(  # a reader's option that writes a file or runs a configured program
    r"--output(?:=|\Z)|--ext-diff\Z|--textconv\Z|--filters\Z|-O|--open-files-in-pager(?:=|\Z)")
NESTED = re.compile(r"(?:^|[\s;|&(/])claude(?:\s|$)", re.M)  # a Claude Code session the command starts
TYPED = re.compile(r"(?:^|[\s\"'`(])/harness(?:\s+(?:on|off|status)\b|\s*$|[\s\"'`)])", re.M)
SETTINGS_ANY = re.compile(r"settings(?:\.[\w-]+)?\.json")  # check_write's names, in any directory
NAMES_SETTINGS = re.compile(r"(?:^|[/'\"=>])" + SETTINGS_ANY.pattern + r"(?![\w-])")  # a word that names one
PROTECTED = ("env", "hooks", "disableAllHooks", "permissions")  # a settings file's keys that switch hooks
CLAUDE_SETTINGS = re.compile(r"(?:^|/)(?:\.claude/settings(?:\.local)?\.json|\.claude\.json|managed-settings\.json"
                             r"|managed-settings\.d/[^/]+\.json)\Z")  # the CLI's sources, by path
INTERPRETER = re.compile(r"(?:python[\d.]*|node|nodejs|deno|bun|ruby|perl|php|bash|sh|dash|zsh|ksh)\Z")
LITERAL_ECHO = re.compile(r"echo((?:\s+-[nE]+)*)\s+'([^']*)'\s*(>>?|>\|)\s*([\w./~+-]+)")
FALLBACK_REDIRECT = re.compile(r"(?:\d*|&)>>?\|?(.*)\Z", re.S)  # a redirection in text the parser cannot read
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
    d = os.path.dirname(path)
    while True:
        if os.path.isfile(os.path.join(d, "hooks", "lib", "harness_switch.py")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _text(word, env: dict) -> str:
    """A parsed word as text: its static parts, a $NAME `env` holds as its value, any other
    expansion as ${...} (no file name is read from what the shell computes)."""
    return "".join(p.text if p.kind in ("lit", "glob", "brace") else env[p.text] if p.text in env and p.kind == "param"
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


def _git(words: list):
    """None for a command that is not git; for git, past the plain wrappers GIT_WRAPPERS (their
    options read from hooks/lib/shell_parse.py's WRAPPERS) and its global options (-C, -c,
    --git-dir, --work-tree, --no-pager, -P, --literal-pathspecs, ...; shell_parse's tables):
    (index of the subcommand word, None when git would run none; its ("-C" | "--work-tree", dir)
    options in order, an `env -C` as a -C; whether a -c / --config-env sets a key naming a
    program (GIT_PROGRAM_KEY) or a -c value starts with `!`; whether an assignment before git
    hands it config or an external diff)."""
    i, dirs, env = 0, [], False
    while i < len(words):
        w = words[i]
        if ASSIGNMENT.match(w):
            env = env or bool(re.match(GIT_CONFIG_ENV, w))
            i += 1
            continue
        name = os.path.basename(w)
        if name not in GIT_WRAPPERS:
            break
        spec, nargs = shell_parse.WRAPPERS[name] or ({"bool": set(), "val": set()}, 0)
        i += 1
        while i < len(words) and words[i].startswith("-") and words[i] != "-":
            opt = words[i]
            i += 1
            if opt == "--":
                break
            if opt in spec["val"]:
                value, i = (words[i] if i < len(words) else ""), i + 1
            elif opt.startswith("--") and "=" in opt and opt.split("=", 1)[0] in spec["val"]:
                opt, value = opt.split("=", 1)
            else:
                continue
            if name == "env" and opt in ("-C", "--chdir"):
                dirs.append(("-C", value))
        while i < len(words) and ASSIGNMENT.match(words[i]) and name == "env":
            env = env or bool(re.match(GIT_CONFIG_ENV, words[i]))
            i += 1
        i += nargs
    if i >= len(words) or os.path.basename(words[i]) != "git":
        return None
    program, i = False, i + 1
    while i < len(words):
        w = words[i]
        name, eq, value = w.partition("=")
        if w in shell_parse.GIT_GLOBAL_VALUE_OPTS or (eq and w.startswith("--") and name in GIT_EQ_OPTS):
            if w in shell_parse.GIT_GLOBAL_VALUE_OPTS:
                name, value, i = w, (words[i + 1] if i + 1 < len(words) else ""), i + 1
            if name in ("-C", "--work-tree"):
                dirs.append((name, value))
            elif name in ("-c", "--config-env"):
                key, _, val = value.partition("=")
                program = program or bool(GIT_PROGRAM_KEY.match(key)) or (name == "-c" and val.startswith("!"))
        elif w.startswith("-c") and len(w) > 2:  # git takes -c only as its own word: it runs nothing
            key, _, val = w[2:].partition("=")
            return None, dirs, program or bool(GIT_PROGRAM_KEY.match(key)) or val.startswith("!"), env
        elif w.startswith("-") and w not in shell_parse.GIT_GLOBAL_FLAGS:
            return None, dirs, program, env  # an option git does not know: it runs nothing
        elif not w.startswith("-"):
            return i, dirs, program, env
        i += 1
    return None, dirs, program, env


def _git_dirs(words: list, cwd: str) -> list:
    """The directories a git command's paths are read from besides `cwd`: where its -C options,
    read in turn from `cwd`, leave it, and its --work-tree; [] for any other command."""
    out, here = [], cwd
    for opt, d in (_git(words) or (None, ()))[1]:
        if opt == "-C":
            here = _resolve(d, here) if d else here
        out.append(here if opt == "-C" else _resolve(d, here))
    return list(dict.fromkeys(out))


def _read_only(words: list) -> bool:
    git = _git(words)
    if git is not None:  # git reads only through a reading subcommand, after its global options
        sub, _, program, env = git
        if sub is None or program or env:
            return False
        name, rest = words[sub], words[sub + 1:]
        if name == "stash" and (rest[:1] or [""])[0] not in ("list", "show"):
            return False
        return name in GIT_READ_ONLY and "-delete" not in rest and not any(GIT_RUNS_OR_WRITES.match(w) for w in rest)
    words = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
    if not words:
        return True
    head = os.path.basename(words[0])
    output = READER_OUTPUT.get(head)
    return (head in READ_ONLY and "-delete" not in words and "-exec" not in words
            and not (output and any(output.match(w) for w in words[1:])))


def _sed_script(script: str):
    """The files a sed script writes (w, W, an s command's w flag), or None when it runs a
    command (e, an s command's e flag) or is text this reading cannot follow."""
    i, n, files = 0, len(script), []

    def until(i, stop):  # the index of the first unescaped char in `stop` from i (n: none)
        while i < n and script[i] not in stop:
            i += 2 if script[i] == "\\" else 1
        return min(i, n)

    def delimited(i, delim):  # past the closing `delim` of a regex or replacement starting at i; -1: none
        while i < n:
            if script[i] == "\\":
                i += 2
            elif script[i] == delim:
                return i + 1
            elif script[i] == "\n" and delim != "\n":
                return -1
            else:
                i += 1
        return -1

    def address(i):
        if i < n and script[i] in "0123456789":
            while i < n and script[i] in "0123456789~":
                i += 1
        elif i < n and script[i] == "$":
            i += 1
        elif i < n and script[i] in "/\\":
            delim = script[i + 1] if script[i] == "\\" and i + 1 < n else "/"
            i = delimited(i + (2 if script[i] == "\\" else 1), delim)
            while 0 <= i < n and script[i] in "IM":
                i += 1
        return i

    while True:
        while i < n and script[i] in " \t\n;":
            i += 1
        if i >= n:
            return files
        if script[i] == "#":
            i = until(i, "\n")
            continue
        i = address(i)
        if i < 0:
            return None
        if i < n and script[i] == ",":
            i += 1
            while i < n and script[i] in " \t":
                i += 1
            if i < n and script[i] in "+~":
                i += 1
                while i < n and script[i] in "0123456789":
                    i += 1
            else:
                i = address(i)
                if i < 0:
                    return None
        while i < n and script[i] in " \t!":
            i += 1
        if i >= n:
            return None
        c, i = script[i], i + 1
        if c in "{}=dDgGhHnNpPxzF":
            pass
        elif c in "qQlL":
            while i < n and script[i] in " \t0123456789":
                i += 1
        elif c in ":btTv":
            i = until(i, ";\n") if c != ":" else until(i, "\n;")
        elif c in "aicrR":
            i = until(i, "\n")
        elif c in "wW":
            j = until(i, "\n")
            files.append(script[i:j].strip())
            i = j
        elif c in "sy":
            if i >= n or script[i] in "\\\n":
                return None
            delim = script[i]
            i = delimited(i + 1, delim)
            i = delimited(i, delim) if i >= 0 else -1
            if i < 0:
                return None
            while c == "s" and i < n and script[i] in "gpiImM0123456789":
                i += 1
            if c == "s" and i < n and script[i] == "w":
                j = until(i + 1, "\n")
                files.append(script[i + 1:j].strip())
                i = j
        else:
            return None  # e, or a command this reading does not know
        while i < n and script[i] in " \t":
            i += 1
        if i < n and script[i] not in ";\n}#":
            return None


def _sed(plain: list):
    """sed's written files (its w commands) when it writes nothing else; None when it is no
    reader: -i / --in-place, a script file (-f), an e command, an unknown option or text."""
    scripts, operands, it = [], [], iter(plain[1:])
    for w in it:
        if w == "--":
            operands.extend(it)
        elif w in ("-e", "--expression"):
            scripts.append(next(it, ""))
        elif w.startswith("--expression="):
            scripts.append(w.split("=", 1)[1])
        elif w.startswith("--line-length=") or w in SED_LONG:
            continue
        elif w.startswith("--"):
            return None  # --in-place, --file, or an option this reading does not know
        elif w.startswith("-") and len(w) > 1:
            for k, ch in enumerate(w[1:], 1):
                if ch in SED_FLAGS:
                    continue
                if ch in "el":
                    value = w[k + 1:] or next(it, "")
                    scripts += [value] if ch == "e" else []
                    break
                return None  # -i, -f, or an option this reading does not know
        else:
            operands.append(w)
    if not scripts and operands:
        scripts.append(operands[0])
    files = []
    for script in scripts:
        written = _sed_script(script)
        if written is None:
            return None
        files += written
    return files


def _awk(plain: list):
    """An awk command's program text, or None when it is no reader: an option that loads a
    program or rewrites its files (-f, -i inplace, -e, -l, ...), or no program."""
    it = iter(plain[1:])
    for w in it:
        if w == "--":
            return next(it, None)
        if w in ("-F", "-v", "--field-separator", "--assign"):
            next(it, None)
        elif re.fullmatch(r"-[Fv].+|--(?:field-separator|assign)=.*", w):
            continue
        elif w.startswith("-"):
            return None
        else:
            return w
    return None


def _cd_dirs(segments: list, cwd: str) -> list:
    """The directories a command's paths are read from: the call's, and each `cd` / `pushd`
    target, read both from the directory the chain before it leaves (`cd ~ && cd .claude`) and
    from the call's (a `cd` in a subshell, or one that fails, leaves the next where it was). A
    bare `cd` is $HOME."""
    out, here, seen = {cwd: None}, cwd, {}
    for words, _ in segments:
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if not plain or os.path.basename(plain[0]) not in ("cd", "pushd"):
            continue
        args = [w for w in plain[1:] if not w.startswith("-")]
        target = args[0] if args else "~"
        for base in (here, cwd):  # each (target, directory) resolved once: a padded `cd .` costs one
            if (target, base) not in seen:
                seen[(target, base)] = _resolve(target, base)
            out[seen[(target, base)]] = None
        here = seen[(target, here)]
    return list(out)


def _written_by(words: list, written: list, awk: bool = False, interpreter: bool = False) -> list:
    """The words of one simple command that it writes: the paths it writes (`written`), and
    for a reader nothing else (READ_ONLY, git's readers, sed without -i, -f or e; with `awk`, awk
    whose program has no > | or system(); with `interpreter`, an interpreter whose words carry no
    WRITE_SIGN); for cp its destination and each source's name inside it; for any other
    command every word (tee, dd, sed -i, perl -i, mv, rm, ...), with awk's quoted strings and
    sed's w files."""
    plain = [w for w in words if not ASSIGNMENT.match(w)]
    if not plain:
        return list(written)
    head = os.path.basename(plain[0])
    if head == "sed":
        files = _sed(plain)
        return list(written) + (files if files is not None else words)
    if head in AWKS:
        program = _awk(plain)
        if awk and program is not None and not AWK_OUTPUT.search(program):
            return list(written)
        return list(written) + words + AWK_STRING.findall(program or " ".join(plain[1:]))
    if _read_only(words) or (interpreter and INTERPRETER.match(head)
                             and not any(WRITE_SIGN.search(w) for w in plain[1:])):
        return list(written)
    if head == "cp":
        return list(written) + [w for w, _ in _operands(plain, False)]
    return list(written) + words + ([w for w, _ in _operands(plain, True)] if head == "mv" else [])


def writes_settings_file(command: str) -> bool:
    """True when `command` writes a settings*.json file, in any directory: one of the words it
    writes (_written_by; an interpreter whose -c text shows no write reads) names one."""
    return any(NAMES_SETTINGS.search(w) for words, written in _commands(command, "code")
               for w in _written_by(words, written, awk=True, interpreter=True))


def _may_name_settings(token: str) -> bool:
    """Whether `token` can name a settings file or a directory holding one by its spelling alone,
    wherever it is read from: its last component as written is a .json name, .claude,
    managed-settings.d, or `.`, `..` or nothing, which only the directory it is read from resolves.
    Any other word names one only when that component is a link (_named_settings looks)."""
    last = os.path.basename(token.rstrip("/"))
    return last in ("", ".", "..", ".claude", "managed-settings.d") or last.endswith(".json")


def _named_settings(word: str, dirs: list, dirs_too=False, home=None) -> list:
    """The Claude Code settings files `word` names, read from each directory in `dirs`, as written
    and with links resolved; with `dirs_too` (None: when no directory is there now) also a
    directory holding them. The home's own settings files are the rule above's, not these.
    A word whose spelling names none (_may_name_settings) costs one lstat a directory, and a
    path is resolved only where it can name one, so a padded command stays cheap."""
    out, home = [], _settings_files() if home is None else home
    for token in {word, word.split("=", 1)[-1]}:
        token = os.path.expanduser(token)
        spelled = _may_name_settings(token)
        for d in dirs:
            lexical = os.path.normpath(os.path.join(d, token))
            if not spelled and not os.path.islink(lexical):
                continue  # its last name is no settings name, and no link: its real path ends in it too
            real = os.path.realpath(lexical)
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
        head == "gh" and sub in ("pr", "issue", "release"))


def _operands(plain: list, moves: bool) -> list:
    """cp / mv: (word, dirs_too) for the destination, each source's name inside it, and, for mv,
    each source (moved away); cp's sources are only read."""
    sources, dest, it = [], None, iter(plain[1:])
    for w in it:
        if w == "--":
            sources.extend(it)
        elif w in ("-t", "--target-directory"):
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
    reader (_written_by), an interpreter or a commit or PR message (tee, sed -i, rm, ...); cp's
    and mv's destination, and mv's sources. A path is read from the call's directory and every
    `cd`'s (_cd_dirs).
    Each directory, and each word with its kind, is read once: a command padded with repeated
    `cd .` costs what its distinct words cost, not their count times its segments'."""
    segments = list(_commands(command, "shell"))
    dirs = list(dict.fromkeys(_cd_dirs(segments, cwd) + [d for w, _ in segments for d in _git_dirs(w, cwd)]))
    out, seen, home = [], set(), _settings_files()
    for words, written in segments:
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if not plain:
            continue
        head = os.path.basename(plain[0])
        interpreter = INTERPRETER.match(head) and not any(re.fullmatch(r"-[A-Za-z]*i.*", w) for w in plain[1:])
        message, moves = _message(plain), head in ("cp", "mv")
        named = [(w, head in ("rm", "rmdir", "rsync")) for w in
                 (written if (interpreter or message or moves) else _written_by(words, written, awk=True))]
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
    settings, segments = _settings_files(), list(_commands(command, "all", every_word=True))
    cds = [_resolve(".", cwd)] + [_resolve(w[1], cwd) for w, _ in segments if len(w) > 1 and os.path.basename(w[0]) in ("cd", "pushd")]
    dirs, checked = _cd_dirs(segments, cwd), set()
    for words, written in segments:
        git, bases = _git(words), dirs
        if git is not None:
            bases = list(dict.fromkeys(dirs + [g for d in dirs for g in _git_dirs(words, d)]))
            homes = {os.path.dirname(f) for f in settings}
            ran_in = [(_git_dirs(words, d) or [d])[-1] for d in dict.fromkeys(cds)]  # from each `cd`
            if git[2] and any(d == h or d.startswith(h + os.sep) for d in ran_in for h in homes):
                return refuse("this Bash command runs git in the harness home with a -c or --config-env that "
                              "names a program (alias.*, core.hooksPath, core.fsmonitor, core.pager, ...) or a "
                              "`!` value, which can rewrite the home's settings or the switch's state")
        for word in words:
            token = word.split("=", 1)[-1]
            if os.path.basename(token.rstrip("/")) in SWITCH_PROGRAMS and not _read_only(words):
                return refuse("this Bash command runs the switch (%s)" % os.path.basename(token))
        for word in dict.fromkeys(_written_by(words, written)):  # the home's files: only a reader is relaxed
            token = word.split("=", 1)[-1]
            if harness_switch.DIR_NAME in token:
                return refuse("this Bash command changes the switch's state (%s)" % harness_switch.DIR_NAME)
            for base in bases:
                if (token, base) in checked:
                    continue
                checked.add((token, base))
                path = _resolve(token, base)
                if _in_state(path):
                    return refuse("this Bash command changes the switch's state (%s)" % harness_switch.DIR_NAME)
                if path in settings and not _allow_settings(cwd):
                    return refuse("this Bash command writes the harness home's %s" % os.path.basename(path))
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
