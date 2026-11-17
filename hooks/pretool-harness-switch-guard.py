#!/usr/bin/env python3
"""PreToolUse (a rule of hooks/pretool-write-gate.py, every tool): only the owner switches the harness.

The owner's typed /harness off|on reaches hooks/userprompt-harness-switch.sh, a UserPromptSubmit
hook: the one event an agent cannot produce. This rule refuses, for the main agent and every
subagent, each other path by which an agent call could switch the harness or fake a switch:

  Skill / SlashCommand  invoking the harness command (its settings deny and its
                        disable-model-invocation say the same)
  Bash                  running scripts/harness-switch or the switch hook (an execution only:
                        the command word, an interpreter's script operand or stdin, source / .,
                        a text runner's operand; matched by name, real path, inode or content),
                        or writing it; naming it (sed -n, shellcheck, bash -n) is free; writing the switch's
                        state <H>/.harness-switch/ (a word the command writes, read from the call's
                        directory and every `cd`'s, as below; reading it is free); typing `/harness on|off`
                        into a Claude Code session the command starts (`claude` run as a command, but
                        --version, --help, doctor, mcp, config, with /harness anywhere in it); writing the home's
                        settings files (settings.json, settings.machine.json, settings.local.json);
                        writing disableAllHooks into any settings*.json, in any project. A command
                        writes only the words it writes (_written_by: a redirect's target, cp's
                        destination, sed's w file, every word of any command but a reader), never
                        a `>` elsewhere: `grep x ~/.claude/settings.json > /tmp/out` reads
  Write / Edit / MultiEdit / NotebookEdit
                        a file under <H>/.harness-switch/; the home's settings files; any
                        settings*.json whose resulting document sets disableAllHooks truthy
                        (a falsy value passes; an unreadable document naming it does not); a
                        file outside a harness checkout that names the switch's state: any kind
                        but prose (.md, .txt, .rst), where only a line that writes it counts
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

import collections  # noqa: E402
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
                 "grep", "rev-parse", "stash", "ls-tree", "rev-list", "shortlog", "reflog", "whatchanged",
                 "diff-tree", "diff-index", "diff-files", "annotate", "name-rev", "describe", "merge-base",
                 "for-each-ref", "show-ref", "cherry", "range-diff", "count-objects", "verify-commit",
                 "verify-tag", "show-branch", "check-ignore", "check-mailmap", "check-ref-format", "var"}
GIT_WRAPPERS = ("env", "command", "exec", "nohup", "setsid", "nice", "ionice", "stdbuf", "timeout", "time",
                "xargs", "sudo", "doas")  # a wrapper whose inner git is judged as git
GIT_ASSIGNING_WRAPPERS = ("env", "sudo")  # a wrapper that takes NAME=value words before its command
GIT_EQ_OPTS = shell_parse.GIT_GLOBAL_VALUE_OPTS | {"--exec-path", "--list-cmds"}  # git's options that take =value
GIT_PROGRAM_KEY = re.compile(  # a config key whose value names a program git runs, or more config
    r"(?i)(?:alias|pager|include|includeif|difftool|mergetool|sendemail|uploadpack|receivepack|sequence"
    r"|interactive|uploadarchive|instaweb|web)\.|core\.(?:hookspath|fsmonitor|sshcommand|pager|editor|askpass"
    r"|gitproxy|alternaterefscommand)\Z|(?:diff|merge)\.(?:.+\.)?(?:external|textconv|command|driver|tool)\Z"
    r"|filter\..+\.(?:clean|smudge|process)\Z|(?:man|browser)\..+\.(?:cmd|path)\Z|submodule\..+\.update\Z"
    r"|remote\..+\.(?:uploadpack|receivepack|vcs)\Z|protocol\.(?:.+\.)?allow\Z"
    r"|gpg\.(?:[^.]+\.)?program\Z|gpg\.ssh\.defaultkeycommand\Z"
    r"|trailer\..+\.(?:cmd|command)\Z|tar\..+\.command\Z|imap\.tunnel\Z|guitool\..+\.cmd\Z"
    r"|(?:diff|merge)\.guitool\Z|core\.attributesfile\Z|init\.templatedir\Z|http\.(?:.+\.)?sslkeylogfile\Z")
GIT_HELPER_KEY = re.compile(r"(?i)credential\.(?:.+\.)?helper\Z")  # a program unless its value is empty
GIT_VIEWER_KEY = re.compile(r"(?i)(?:core\.(?:pager|editor)|pager\..+|sequence\.editor)\Z")  # a pager or editor
GIT_VIEWERS = ("", "cat", "less", "more")  # a pager or editor value that only shows text
GIT_BOOLEAN_KEY = re.compile(r"(?i)core\.fsmonitor\Z|pager\..+\Z")  # a key whose boolean value names no program
GIT_BOOLEANS = ("true", "false", "yes", "no", "on", "off", "1", "0")
GIT_PROGRAM_ENV = ("GIT_CONFIG", "GIT_EXTERNAL_DIFF", "GIT_EXEC_PATH", "GIT_SSH_COMMAND", "GIT_SSH",
                   "GIT_ASKPASS", "SSH_ASKPASS")  # a variable whose value is a program git runs, or config
GIT_EDITOR_ENV = ("GIT_EDITOR", "EDITOR", "VISUAL", "GIT_SEQUENCE_EDITOR")
GIT_VIEWER_ENV = ("GIT_PAGER", "PAGER") + GIT_EDITOR_ENV
GIT_EDITOR_FREE = GIT_READ_ONLY - {"add"}  # readers that start no editor (add -e / -p does)
GIT_TREE_ENV = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")  # where git finds its repository and work tree
GIT_TRACE_ENV = re.compile(r"GIT_TRACE\w*\Z")  # a trace variable: an absolute path is a file git appends to
GIT_CARRIED = re.compile(  # a variable that hands git a program, config or repository: its value matters
    r"(?:GIT_(?:EXTERNAL_DIFF|SSH_COMMAND|SSH|ASKPASS|PAGER|EDITOR|SEQUENCE_EDITOR|EXEC_PATH|DIR|COMMON_DIR"
    r"|WORK_TREE|CONFIG\w*|TRACE\w*)|SSH_ASKPASS|PAGER|EDITOR|VISUAL|HOME|XDG_CONFIG_HOME)\Z")
UNKNOWN = "/?unknown-value?"  # the value of a variable the command sets in a way not read here
LESS_ENV = re.compile(r"\bLESS\w*")  # less's own environment: LESS, LESSOPEN, LESSKEY, ...
GIT_CONFIG_SOURCE = re.compile(  # where git reads its global and system config from (GIT_TREE_ENV aside)
    r"(?:HOME|XDG_CONFIG_HOME|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM)=")
GIT_WRITING_LONG = ("output", "ext-diff", "textconv", "filters")  # a reader's options that write or run a program
GIT_ABBREVIATING = {"grep": ("textconv", "open-files-in-pager"), "cat-file": ("textconv", "filters"),
                    "range-diff": ("output", "ext-diff", "textconv")}  # readers whose options git abbreviates
GIT_HARMLESS_LONG = ("text",)  # a reader's own option spelled as a prefix of one of those
GIT_GREP_ARG_SHORTS = "efABCm"  # git grep's short options whose value is the rest of the word
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


def _commands(command, bodies: str, every_word: bool = False, depth: int = 0, sites: list | None = None,
              quoted: bool | None = None):
    """(words, written) for each simple command `command` runs, as hooks/lib/shell_parse.py reads it:
    its words as text (assignments, words, then each redirection's operator and target) and the
    paths shell_parse.write_targets says it writes. A -c or eval payload, a substitution and a
    heredoc a shell reads are commands; so is any other heredoc's body where `bodies` keeps it
    ("all"; "code": unless it feeds a commit, tag or PR message; "shell": none). With `every_word`
    a word holding a space or ; | & is read as commands too, unless it is a reader's operand (echo,
    printf, grep, rg, ...: _read_only; an assignment before it, LESSOPEN=..., stays read) and
    nothing in the command runs text (_runs_text): a note that mentions a command is no command. A $NAME is read from the call's
    environment or an assignment before it; text the parser cannot read is split on whitespace,
    a word after a redirection operator, or attached to one, written. `command` may be a parsed
    shell_parse.Script; `sites` collects each yield's SimpleCommand (a re-read word's own)."""
    script = command if isinstance(command, shell_parse.Script) else shell_parse.parse(command)
    env, message, targets = dict(os.environ), [], {}
    if every_word and quoted is None:
        quoted = _runs_text(script)
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
        n = len(words)
        for r in cmd.redirects:
            words += [(r.io or "") + r.op, _text(r.target, env)] if r.target is not None else []
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if plain and _message(plain):
            message.append(level)
        if sites is not None:
            sites.append(cmd)
        yield words, written
        reread = not every_word or quoted or not plain or not _read_only(plain)  # a reader's text is no code
        for w in (words if reread else [w for w in words if ASSIGNMENT.match(w)]) if every_word and depth < 3 else ():
            if any(c in w for c in " ;|&\n"):
                yield from _commands(w, bodies, every_word, depth + 1, sites, quoted)
        shell = shell_parse.resolve(cmd).payload_kind == "heredoc_shell"
        for r in cmd.redirects if bodies == "all" or (bodies == "code" and not message) else ():
            if r.hd is not None and not shell and depth < 3 and reread:
                yield from _commands(r.hd.body, bodies, every_word, depth + 1, sites, quoted)
    for word in [w for ws in targets.values() for w in ws]:  # a redirection of a compound command
        if sites is not None:
            sites.append(None)
        yield [">", _text(word, env)], [_text(word, env)]
    for line in (command if isinstance(command, str) else script.source or "").splitlines() \
            if script.error is not None else ():
        words = line.split()
        if sites is not None:
            sites.append(None)
        yield words, [m.group(1) or nxt for w, nxt in zip(words, words[1:] + [""]) for m in [FALLBACK_REDIRECT.match(w)] if m]


TEXT_RUNNERS = frozenset({"source", ".", "eval", "xargs", "parallel", "watch", "ssh", "su", "sudo", "doas",
                          "runuser", "script", "flock", "chroot", "unshare", "nsenter", "busybox", "expect",
                          "tmux", "screen", "at", "batch", "crontab", "exec", "trap", "alias"})


def _runs_text(script) -> bool:
    """Whether a command in `script` may run text a reader in the same command prints: a shell or
    an interpreter (on a payload, a file or stdin), a program that runs its operands as commands
    (TEXT_RUNNERS), or a computed or path-named program."""
    for site in shell_parse.walk(script):
        head = site.cmd.head()
        if head is None:
            continue
        value = head.value()
        if site.dynamic or value is None or "/" in value:
            return True
        for name in {os.path.basename(value), shell_parse.resolve(site.cmd).name or ""}:
            if name in TEXT_RUNNERS or name in shell_parse.SHELLS or INTERPRETER.match(name) \
                    or shell_parse._SHELL_LIKE_RE.fullmatch(name):
                return True
    return False


SWITCH_FILES = (os.path.join(HOME, "scripts", "harness-switch"), os.path.join(HOME, "hooks", "userprompt-harness-switch.sh"))
SESSIONLESS = ("--version", "-v", "--help", "-h", "doctor", "mcp", "config")  # claude's forms that start no session
PY_READERS = ("py_compile", "compileall", "tokenize", "tabnanny", "pyclbr", "dis", "ast")  # python -m: it reads
INTERP_VALUE = {"python": "WXQ", "perl": "IM", "ruby": "IrCE", "node": "r", "nodejs": "r", "bun": "r", "php": "dc",
                "shell": "oO"}  # short options whose value is the next word
INTERP_CODE_OPTS = {"python": "c", "perl": "eE", "ruby": "e", "node": "ep", "nodejs": "ep", "bun": "e", "php": "rB",
                    "shell": "c"}  # code on the command line: the script operand is no script
STDIN_SCRIPT = ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0")


def _switch_identity():
    out = []
    for path in SWITCH_FILES:
        try:
            st = os.stat(path)
            with open(path, "rb") as fh:
                out.append((os.path.realpath(path), (st.st_dev, st.st_ino), st.st_size, fh.read()))
        except OSError:
            continue
    return out


def _is_switch(text: str, dirs: list, ident: list) -> bool:
    """Whether `text` names the switch program: its name, or a file with its real path, inode or content."""
    if not text or "\0" in text:
        return False
    if os.path.basename(text.rstrip("/")) in SWITCH_PROGRAMS:
        return True
    for d in dirs:
        path = _resolve(text, d)
        try:
            st = os.stat(path)
        except (OSError, ValueError):
            continue
        if not os.path.isfile(path):
            continue
        for real, ino, size, content in ident:
            if path == real or (st.st_dev, st.st_ino) == ino:
                return True
            if st.st_size == size:
                try:
                    with open(path, "rb") as fh:
                        if fh.read(size + 1) == content:
                            return True
                except OSError:
                    pass
    return False


def _feeds_switch(word, env: dict, dirs: list, ident: list) -> bool:
    """Whether a word is the switch program or prints it: its text names it, or a substitution in it
    (a process or command substitution) has a word that names it."""
    if word is None:
        return False
    if _is_switch(_text(word, env), dirs, ident):
        return True
    for p in shell_parse.active_parts(word.parts):
        if p.body is not None and _names_switch(p.body, env, dirs, ident):
            return True
    return False


def _names_switch(script, env: dict, dirs: list, ident: list) -> bool:
    """Whether any word of any command in `script` (its substitutions included) names the switch program."""
    for site in shell_parse.walk(script):
        for w in list(site.cmd.words) + [r.target for r in site.cmd.redirects if r.target is not None]:
            if _is_switch(_text(w, env), dirs, ident):
                return True
        for r in site.cmd.redirects:
            if r.hd is not None and any(_is_switch(t, dirs, ident) for t in r.hd.body.split()):
                return True
    return False


def _prev_stage(site):
    """The pipeline stage before `site`'s command, as a one-stage Script, or None."""
    for pl, _sep in getattr(site.script, "items", ()):
        for k, stage in enumerate(pl.stages):
            if stage is site.cmd:
                return shell_parse.Script([(shell_parse.Pipeline([pl.stages[k - 1]], []), None)],
                                          site.script.source, None) if k else None
    return None


def _kind(name: str):
    if name in shell_parse.SHELLS or shell_parse._SHELL_LIKE_RE.fullmatch(name):
        return "shell"
    m = INTERPRETER.match(name)
    if not m:
        return None
    base = re.match(r"[a-z]+", name).group(0)
    return "python" if base == "python" else "shell" if base in ("bash", "sh", "dash", "zsh", "ksh") else base


def _interpreter_runs_switch(site, res, kind: str, env: dict, dirs: list, ident: list) -> bool:
    """Whether an interpreter or shell runs the switch program: as its script operand, or on its stdin."""
    args, i, check = list(res.args), 0, False
    script = None
    while i < len(args):
        v = args[i].value()
        if v is None or not v.startswith(("-", "+")) or v in ("-",):
            script = args[i]
            break
        if v == "--":
            script = args[i + 1] if i + 1 < len(args) else None
            break
        if v.startswith("--"):
            i += 1
            continue
        flags = v[1:]
        if kind == "python" and "m" in flags:
            mod = flags.split("m", 1)[1] or (args[i + 1].value() if i + 1 < len(args) else None)
            if mod in PY_READERS:
                return False
            rest = args[i + (1 if flags.split("m", 1)[1] else 2):]
            return any(_feeds_switch(w, env, dirs, ident) for w in rest)  # a module run on the switch
        if any(c in INTERP_CODE_OPTS.get(kind, "") for c in flags):
            return False  # code on the command line; its operands are arguments
        if kind == "shell" and v.startswith("-") and "n" in flags:
            check = True  # bash -n: read, not run
        if flags and flags[-1] in INTERP_VALUE.get(kind, ""):
            i += 2
            continue
        i += 1
    if check:
        return False
    if script is not None and script.value() not in STDIN_SCRIPT:
        return _feeds_switch(script, env, dirs, ident)
    for r in site.cmd.redirects:  # stdin: a file, a here-string, a heredoc
        if r.fd != 0:
            continue
        if r.op in ("<", "<>", "<<<") and _feeds_switch(r.target, env, dirs, ident):
            return True
        if r.hd is not None and (any(_is_switch(t, dirs, ident) for t in r.hd.body.split()) or any(
                p.body is not None and _names_switch(p.body, env, dirs, ident) for p in r.hd.expansions)):
            return True
    prev = _prev_stage(site) if "pipe" in site.fed else None
    return prev is not None and _names_switch(prev, env, dirs, ident)


def _executions(script, command: str, dirs: list, ident: list, depth: int = 0):
    """The reason a command in `script` runs the switch program or starts a Claude Code session
    given /harness, or None. Only executions count: the command word (wrappers peeled), an
    interpreter's or shell's script operand or stdin, source / ., and a text runner's operands."""
    env = dict(os.environ)
    typed = bool(TYPED.search(command))
    for site in shell_parse.walk(script):
        cmd = site.cmd
        for a in cmd.assignments if not cmd.words else ():
            env.pop(a.name, None) if a.static_value() is None else env.update({a.name: a.static_value()})
        res = shell_parse.resolve(cmd)
        head = res.head
        if head is None:
            continue
        head_text = _text(head, env)
        if _feeds_switch(head, env, dirs, ident):
            return "runs the switch (%s)" % os.path.basename(head_text)
        name = os.path.basename(head_text)
        args = [_text(w, env) for w in res.args]
        if typed and (name == "claude" or (head.value() is None and "claude" in head.raw.text)) \
                and (args[:1] or [""])[0] not in SESSIONLESS:
            return "types /harness into a Claude Code session it starts"
        if name in ("source", ".") and res.args and _feeds_switch(res.args[0], env, dirs, ident):
            return "runs the switch (%s %s)" % (name, os.path.basename(args[0]))
        kind = _kind(name)
        if kind and _interpreter_runs_switch(site, res, kind, env, dirs, ident):
            return "runs the switch (%s on it)" % name
        if name in TEXT_RUNNERS and depth < 3:  # a program that runs its operands as commands
            for w, t in zip(res.args, args):
                if _feeds_switch(w, env, dirs, ident):
                    return "runs the switch (%s %s)" % (name, os.path.basename(t))
                if typed and os.path.basename(t) == "claude":
                    return "types /harness into a Claude Code session it starts"
                if any(c in t for c in " ;|&\n"):
                    why = _executions(shell_parse.parse(t), command, dirs, ident, depth + 1)
                    if why:
                        return why
            for r in cmd.redirects:
                if r.hd is not None:
                    why = _executions(shell_parse.parse(r.hd.body), command, dirs, ident, depth + 1)
                    if why:
                        return why
    return None


def _writes_switch(words: list, written: list) -> bool:
    """Whether one command writes the switch program: a word it writes, or perl / ruby -i's operands."""
    plain = _argv(words)
    inplace = bool(plain) and os.path.basename(plain[0]) in ("perl", "ruby") and any(
        re.match(r"-[A-Za-z]*i", w) for w in plain[1:])
    return any(os.path.basename(w.split("=", 1)[-1].rstrip("/")) in SWITCH_PROGRAMS
               for w in list(written) + (plain if inplace else []))


GitCall = collections.namedtuple("GitCall", "sub dirs program env source gitdirs traces")


def _harmless_viewer(value: str, less_env: bool = False) -> bool:
    """Whether a pager or editor value only shows text: exactly cat, less, more or empty, or less
    or more with option flags alone (`less -R`, `less -FRX`): no operand, no `+` command, no log
    file (-o, -O, --log-file) or lesskey file (-k, --lesskey-*), nothing the shell reads as code,
    and no LESS* variable (LESS, LESSOPEN, LESSKEY, ...) set or named in the same command."""
    v = value.strip()
    if v in GIT_VIEWERS:
        return True
    parts = v.split()
    if less_env or re.search(r"[^\w\s./=,-]", v) or parts[0] not in ("less", "more"):
        return False
    for p in parts[1:]:
        if not p.startswith("-") or p in ("-", "--"):
            return False
        if p.startswith("--"):
            name = p[2:].partition("=")[0].lower()
            if any(k.startswith(name) or name.startswith(k) for k in ("log-file", "lesskey")):
                return False
        elif any(c in "oOk" for c in p[1:]):
            return False
    return True


def _program_setting(opt: str, setting: str, less_env: bool = False) -> bool:
    """Whether a -c (`opt` "-c", `setting` "key=value") or --config-env ("key=VAR") hands git a
    program: a key GIT_PROGRAM_KEY names, a non-empty credential helper (an empty one turns the
    helpers off; --config-env's value is unknown), or a -c value starting with `!`. A -c pager or
    editor that only shows text (_harmless_viewer) and a boolean core.fsmonitor or pager.<cmd>
    name none; an editor key is judged whatever the subcommand."""
    key, eq, val = setting.partition("=")
    if opt == "-c" and val.startswith("!"):
        return True
    if opt == "-c" and GIT_BOOLEAN_KEY.match(key) and (not eq or val.strip().lower() in GIT_BOOLEANS):
        return False
    if opt == "-c" and eq and GIT_VIEWER_KEY.match(key) and _harmless_viewer(val, less_env):
        return False
    if GIT_PROGRAM_KEY.match(key):
        return True
    return bool(GIT_HELPER_KEY.match(key)) and (opt != "-c" or not eq or val.strip() != "")


def _config_pairs(value: str):
    """GIT_CONFIG_PARAMETERS's 'key'='value' pairs as "key=value" settings; None when unreadable."""
    pairs, rest = [], value.strip()
    while rest:
        m = re.match(r"'([^']*)'(?:='([^']*)')?\s*", rest)
        if not m:
            return None
        pairs.append(m.group(1) + ("=" + m.group(2) if m.group(2) is not None else ""))
        rest = rest[m.end():]
    return pairs


def _env_program(assignments: list, editor: bool = True, less_env: bool = False) -> bool:
    """Whether NAME=value words hand git a program or config naming one, as a -c would
    (_program_setting): GIT_CONFIG_PARAMETERS's pairs, GIT_CONFIG_KEY_<n> with GIT_CONFIG_VALUE_<n>
    (either UNKNOWN is a program), a pager variable that shows more than text (_harmless_viewer),
    an editor variable likewise where the subcommand starts an editor (`editor`), and
    GIT_PROGRAM_ENV's variables."""
    values = dict(w.split("=", 1) for w in assignments if ASSIGNMENT.match(w))
    for name, value in values.items():
        if name in GIT_PROGRAM_ENV:
            return True
        if name in GIT_VIEWER_ENV and (editor or name not in GIT_EDITOR_ENV) and not _harmless_viewer(value, less_env):
            return True
        if name == "GIT_CONFIG_PARAMETERS":
            pairs = _config_pairs(value)
            if pairs is None or any(_program_setting("-c", p, less_env) for p in pairs):
                return True
        if re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", name) and value == UNKNOWN:
            return True
        m = re.fullmatch(r"GIT_CONFIG_KEY_(\d+)", name)
        if m and _program_setting("-c", value + "=" + values.get("GIT_CONFIG_VALUE_" + m.group(1), ""), less_env):
            return True
    return False


def _wrapper_options(name: str, words: list, i: int):
    """A wrapper's options from words[i], as getopt reads them against hooks/lib/shell_parse.py's
    table for it (WRAPPERS, else PEEL): clustered short flags (`env -iu X`, `-0u X`, `-iC dir`),
    a value attached or in the next word, long options with `=value` or a unique abbreviation;
    xargs's -i, -e and -l take an attached value only; env's lone `-` is -i. Returns the index
    after them and their (option, value) pairs."""
    entry = shell_parse.WRAPPERS.get(name) or shell_parse.PEEL.get(name) or ({"bool": set(), "val": set()}, 0)
    spec, out = entry[0], []
    longs = [o for o in set(spec["bool"]) | set(spec["val"]) if o.startswith("--")]
    while i < len(words):
        w = words[i]
        if name == "env" and w == "-":
            i += 1
            continue
        if not w.startswith("-") or w == "-":
            break
        i += 1
        if w == "--":
            break
        if w.startswith("--"):
            opt, eq, val = w.partition("=")
            hits = [opt] if opt in longs else [o for o in longs if o.startswith(opt)]
            opt = hits[0] if len(hits) == 1 else opt
            if opt in spec["val"] and not eq:
                val, i = (words[i] if i < len(words) else ""), i + 1
            out.append((opt, val if opt in spec["val"] else None))
            continue
        for j in range(1, len(w)):
            ch, rest = "-" + w[j], w[j + 1:]
            if name == "xargs" and ch in ("-i", "-e", "-l"):
                out.append((ch, rest))
                break
            if ch in spec["val"]:
                if not rest:
                    rest, i = (words[i] if i < len(words) else ""), i + 1
                out.append((ch, rest))
                break
            out.append((ch, None))
    return i, out


def _git(words: list, pre=(), less_env: bool = False):
    """None for a command that is not git; for git, past the wrappers GIT_WRAPPERS (env, sudo,
    xargs, timeout, ...; their options read by _wrapper_options, NAME=value words after env's and
    sudo's) and its global options (-C, -c, --git-dir, --work-tree, --no-pager, -P,
    --literal-pathspecs, ...; shell_parse's tables), a GitCall: `sub`, the index of the
    subcommand word (None when git would run none); `dirs`, its ("-C" | "--work-tree", dir)
    options in order, an `env -C` / `sudo -D` as a -C; `program`, whether a -c / --config-env
    hands it a program (_program_setting) or --exec-path=<dir> moves where it finds its own
    programs; `env`, whether an assignment before it hands it a program or config naming one
    (_env_program); `source`, whether an assignment before it moves where it reads config from
    (HOME, XDG_CONFIG_HOME, GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM: GIT_CONFIG_SOURCE); `gitdirs`, its
    GIT_DIR= / GIT_COMMON_DIR= and --git-dir values; `traces`, the files GIT_TRACE* variables
    name. A GIT_WORK_TREE= and a -c core.worktree= are --work-tree directories too. `pre` holds
    the GIT_TREE_ENV assignments an earlier export hands it; an editor counts only where the
    subcommand starts one (GIT_EDITOR_FREE); `less_env` as _harmless_viewer's."""
    i, dirs, assigned, source, gitdirs, trees, traces = 0, [], [], False, [], [], []

    def assignment(w):
        nonlocal source
        assigned.append(w)
        name, _, value = w.partition("=")
        if name in ("GIT_DIR", "GIT_COMMON_DIR"):
            gitdirs.append(value)
        elif name == "GIT_WORK_TREE":
            trees.append(("--work-tree", value))
        elif GIT_TRACE_ENV.match(name) and value.startswith(("/", "~")):
            traces.append(value)
        elif GIT_CONFIG_SOURCE.match(w):
            source = True

    for w in pre:
        assignment(w)

    def done(sub):
        editor = not (sub is not None and words[sub] in GIT_EDITOR_FREE)
        program = exec_path or any(_program_setting(o, v, less_env) for o, v in settings)
        return GitCall(sub, dirs + trees, program, _env_program(assigned, editor, less_env), source, gitdirs, traces)

    while i < len(words):
        w = words[i]
        if ASSIGNMENT.match(w):
            assignment(w)
            i += 1
            continue
        name = os.path.basename(w)
        if name not in GIT_WRAPPERS:
            break
        i, opts = _wrapper_options(name, words, i + 1)
        for opt, value in opts:
            if (name, opt) in (("env", "-C"), ("env", "--chdir"), ("sudo", "-D"), ("sudo", "--chdir")):
                dirs.append(("-C", value))
        while i < len(words) and ASSIGNMENT.match(words[i]) and name in GIT_ASSIGNING_WRAPPERS:
            assignment(words[i])
            i += 1
        entry = shell_parse.WRAPPERS.get(name) or shell_parse.PEEL.get(name)
        i += entry[1] if entry and isinstance(entry[1], int) else 0
    if i >= len(words) or os.path.basename(words[i]) != "git":
        return None
    settings, exec_path, i = [], False, i + 1
    while i < len(words):
        w = words[i]
        name, eq, value = w.partition("=")
        if w in shell_parse.GIT_GLOBAL_VALUE_OPTS or (eq and w.startswith("--") and name in GIT_EQ_OPTS):
            if w in shell_parse.GIT_GLOBAL_VALUE_OPTS:
                name, value, i = w, (words[i + 1] if i + 1 < len(words) else ""), i + 1
            if name in ("-C", "--work-tree"):
                dirs.append((name, value))
            elif name == "--git-dir":
                gitdirs.append(value)
            elif name == "--exec-path":
                exec_path = True  # git runs its subcommands from that directory, as GIT_EXEC_PATH
            elif name in ("-c", "--config-env"):
                settings.append((name, value))
                if name == "-c" and value.partition("=")[0].lower() == "core.worktree":
                    dirs.append(("--work-tree", value.partition("=")[2]))
        elif w.startswith("-c") and len(w) > 2:  # git takes -c only as its own word: it runs nothing
            settings.append(("-c", w[2:]))
            return done(None)
        elif w.startswith("-") and w not in shell_parse.GIT_GLOBAL_FLAGS:
            return done(None)  # an option git does not know
        elif not w.startswith("-"):
            return done(i)
        i += 1
    return done(None)


def _git_dirs(words: list, cwd: str) -> list:
    """The directories a git command's paths are read from besides `cwd`: where its -C options,
    read in turn from `cwd`, leave it, and its --work-tree; [] for any other command."""
    out, here = [], cwd
    for opt, d in (_git(words) or GitCall(None, (), False, False, False, [], []))[1]:
        if opt == "-C":
            here = _resolve(d, here) if d else here
        out.append(here if opt == "-C" else _resolve(d, here))
    return list(dict.fromkeys(out))


def _git_writing_option(name: str, word: str) -> bool:
    """Whether `word`, an argument of the reading subcommand `name`, writes a file or runs a
    program: --output, --ext-diff, --textconv, --filters, or, for the readers whose options git
    abbreviates (GIT_ABBREVIATING: git grep, cat-file, range-diff), a prefix of one of theirs
    (`--textc`, `--filt`, grep's `--open=<cmd>`; `--text`, an option of its own, aside); log,
    rev-list, diff and the others take no abbreviation, so their `--filter=` is its own option;
    for git grep alone, -O in a cluster of short options (-O, -nO<cmd>; -eO's O is a pattern).
    Elsewhere -O<file> names a diff's order file."""
    if word.startswith("--"):
        opt = word[2:].partition("=")[0]
        if opt in GIT_WRITING_LONG + GIT_ABBREVIATING.get(name, ()):
            return True
        return bool(opt) and opt not in GIT_HARMLESS_LONG and any(w.startswith(opt) for w in GIT_ABBREVIATING.get(name, ()))
    if name != "grep" or not word.startswith("-") or len(word) < 2:
        return False
    for c in word[1:]:
        if c == "O":
            return True
        if c in GIT_GREP_ARG_SHORTS:
            return False
    return False


def _grep_opens_program(word: str, less_env: bool = False) -> bool:
    """Whether `word`, an argument of git grep, opens the matching files in a program it names:
    -O<cmd> in a short-option cluster, or --open-files-in-pager=<cmd> spelled by any prefix git
    accepts (`--open=<cmd>`), unless the value only shows text (_harmless_viewer). With no value
    git uses the configured pager."""
    if word.startswith("--"):
        name, eq, value = word[2:].partition("=")
        return bool(eq) and len(name) >= 2 and "open-files-in-pager".startswith(name) and not _harmless_viewer(value, less_env)
    if not word.startswith("-") or len(word) < 2:
        return False
    for j, c in enumerate(word[1:], 1):
        if c == "O":
            return not _harmless_viewer(word[j + 1:], less_env)
        if c in GIT_GREP_ARG_SHORTS:
            return False
    return False


def _read_only(words: list) -> bool:
    git = _git(words)
    if git is not None:  # git reads only through a reading subcommand, after its global options
        if git.sub is None or git.program or git.env:
            return False
        name, rest = words[git.sub], words[git.sub + 1:]
        if name == "stash" and (rest[:1] or [""])[0] not in ("list", "show"):
            return False
        if name == "reflog" and ("expire" in rest or "delete" in rest):
            return False
        return name in GIT_READ_ONLY and "-delete" not in rest and not any(_git_writing_option(name, w) for w in rest)
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

    def bracket(i):  # past the `]` closing a bracket expression whose `[` is at i; -1: unsure
        j = i + 1
        j += 1 if j < n and script[j] == "^" else 0
        j += 1 if j < n and script[j] == "]" else 0
        while j < n:
            ch = script[j]
            if ch == "[" and j + 1 < n and script[j + 1] in ":.=":
                close = script.find(script[j + 1] + "]", j + 2)
                if close < 0:
                    return -1
                j = close + 2
            elif ch == "]":
                return j + 1
            elif ch == "\\":  # GNU reads `\<delim>` as the delimiter; `\]` it reads otherwise than POSIX
                if j + 1 >= n or script[j + 1] in "]\n":
                    return -1
                j += 2
            elif ch == "\n":
                return -1
            else:
                j += 1
        return -1

    def delimited(i, delim, regex=False):  # past the closing `delim` of a regex (`regex`: its bracket
        while i < n:                        # expressions followed) or a replacement starting at i; -1: none
            if script[i] == "\\":
                i += 2
            elif regex and script[i] == "[":
                i = bracket(i)
                if i < 0:
                    return -1
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
            i = delimited(i + (2 if script[i] == "\\" else 1), delim, regex=True)
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
            i = delimited(i + 1, delim, regex=c == "s")
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


def _sed_w_words(plain: list) -> list:
    """For sed that is no reader: the text after each `w` / `W` in its words, to the end of the
    line, any of which may be a file a script this reading cannot follow writes."""
    return [w[m.end():].split("\n", 1)[0].strip() for w in plain[1:] for m in re.finditer(r"[wW]", w)]


def _awk(plain: list):
    """An awk command's program text, or None when it is no reader: an option that loads a
    program or rewrites or writes files (-f / --file, -i inplace, -e, -l, -o, -p, ...), or no program.
    -v / --assign and -F / --field-separator take a value (spaced, attached or after `=`); `--`
    ends the options."""
    it = iter(plain[1:])
    for w in it:
        if w == "--":
            return next(it, None)
        if w in ("-F", "-v", "--field-separator", "--assign"):
            next(it, None)
        elif re.fullmatch(r"-[Fv].+|--(?:field-separator|assign)=.*", w, re.S):
            continue
        elif w.startswith("-") and w != "-":
            return None
        else:
            return w
    return None


TAR_SHORT = set("cvzjJapht")  # tar's short flags that read (create or list) and write no file but -f's
TAR_LONG = ("--create", "--list", "--gzip", "--bzip2", "--xz", "--zstd", "--auto-compress", "--verbose",
            "--dereference", "--preserve-permissions")


def _tar(plain: list):
    """tar that creates or lists an archive, reading its operands: the archive it writes (-f's,
    none for stdout), or None for any other tar (-x, -C, --to-command, -I, an unknown option)."""
    args, files, mode = plain[1:], [], False
    if args and not args[0].startswith("-"):  # the old style: `tar czf out.tgz ...`
        args = ["-" + args[0]] + args[1:]
    it = iter(args)
    for w in it:
        if w == "--":
            break
        if w.startswith("--"):
            name, eq, value = w.partition("=")
            if name == "--file":
                files.append(value if eq else next(it, ""))
            elif name in ("--exclude",) and eq:
                continue
            elif w in TAR_LONG:
                mode = mode or w in ("--create", "--list")
            else:
                return None
        elif w.startswith("-") and len(w) > 1:
            for k, ch in enumerate(w[1:], 1):
                if ch == "f":
                    files.append(w[k + 1:] or next(it, ""))
                    break
                if ch not in TAR_SHORT:
                    return None
                mode = mode or ch in "ct"
        # an operand: a file tar reads
    if not mode:
        return None
    return [f for f in files if f and f != "-"]


def _tar_extracts(plain: list) -> list:
    """For tar that is no reader (-x, -r, --to-command, ...): the settings files it may write as
    archive members right in each directory it extracts into (-C / --directory, else its own), the
    member names the archive holds being unknown here (a member under a subdirectory is not seen)."""
    dirs, it = [], iter(plain[1:])
    for w in it:
        m = re.fullmatch(r"-[A-Za-z]*C(.*)", w, re.S)
        if w in ("-C", "--directory") or (m and not w.startswith("--")):
            value = (m.group(1) if m else "") or next(it, None)
            dirs += [value] if value else []
        elif w.startswith("--directory="):
            dirs.append(w.split("=", 1)[1])
    return [os.path.join(d, n) for d in dirs or ["."] for n in SETTINGS_NAMES]


INTERP_CODE = {"python": "c", "perl": "eE", "ruby": "e", "node": "ep", "nodejs": "ep", "bun": "e", "php": "r"}
INTERP_FLAGS = {"python": "IBsSuqEOd", "perl": "nplawsT", "ruby": "nplaw", "node": "", "nodejs": "", "bun": "",
                "php": "n"}
INTERP_DYNAMIC = re.compile(  # code whose effect this reading cannot see from its text
    r"\b(?:chr|getattr|setattr|eval|exec|compile|__import__|importlib|globals|locals|vars|fromCharCode|send"
    r"|public_send|instance_eval|class_eval|const_get|unpack|pack|decode|codecs|base64|bytes|bytearray)\b")
OPEN_CALL = re.compile(r"\bopen\s*\(")
OPEN_LITERAL = re.compile(  # an open() argument after the path that reads: a literal read mode or other literal
    r"\s*(?:(?:mode\s*=\s*)?[rbuRBU]*(?:'[rbtU]*'|\"[rbtU]*\")|(?:encoding|errors|newline|buffering)\s*="
    r"\s*(?:'[^']*'|\"[^\"]*\"|-?\d+|None)|-?\d+)\s*\Z")


def _open_reads(code: str) -> bool:
    """Each open( call in `code` passes the path alone or with a literal read mode."""
    for m in OPEN_CALL.finditer(code):
        i, depth, quote, args, start = m.end(), 1, None, [], m.end()
        while i < len(code) and depth:
            ch = code[i]
            if quote:
                quote = None if ch == quote else quote
                i += 1 if ch != "\\" else 2
                continue
            if ch in "'\"":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 1:
                args.append(code[start:i])
                start = i + 1
            i += 1
        if depth:
            return False
        args.append(code[start:i - 1])
        if not all(OPEN_LITERAL.match(a) for a in args[1:] if a.strip()):
            return False
    return True


def _interpreter_reads(plain: list) -> bool:
    """For disableAllHooks: an interpreter provably read-only, one whose -c / -e code shows no write
    (WRITE_SIGN), no computed call (INTERP_DYNAMIC) and no open() with a mode other than a
    literal read; or `python -m json.tool` with one file. A script file or stdin is never provably
    read-only; a shell's -c code is (its commands are read on their own)."""
    head = os.path.basename(plain[0])
    if shell_parse._SHELL_LIKE_RE.fullmatch(head):
        return not any(WRITE_SIGN.search(w) for w in plain[1:])
    lang = re.sub(r"[\d.]+\Z", "", head)
    code_opts, flags, it, code = INTERP_CODE.get(lang, ""), INTERP_FLAGS.get(lang, ""), iter(plain[1:]), None
    for w in it:
        if lang in ("node", "nodejs", "bun") and w in ("--eval", "--print"):
            code = next(it, None)
            break
        if lang == "python" and w == "-m":
            rest = list(it)
            return rest[:1] == ["json.tool"] and len([r for r in rest[1:] if not r.startswith("-")]) <= 1 \
                and all(r in ("--sort-keys", "--compact", "--no-ensure-ascii") for r in rest[1:] if r.startswith("-"))
        if not (w.startswith("-") and len(w) > 1 and not w.startswith("--")):
            return False  # a script file, `-` (stdin) or a long option
        if all(ch in flags for ch in w[1:]):
            continue
        if not code_opts or w[-1] not in code_opts or any(ch not in flags for ch in w[1:-1]):
            return False
        code = next(it, None)
        break
    return code is not None and not WRITE_SIGN.search(code) and not INTERP_DYNAMIC.search(code) \
        and _open_reads(code)


CD_HEADS = ("cd", "pushd", "popd")


def _cd_at(words: list):
    """The index of a cd / pushd / popd word in a command's words (past its assignments and a
    `builtin` or `command` before it), or None."""
    i = 0
    while i < len(words) and ASSIGNMENT.match(words[i]):
        i += 1
    while i < len(words) - 1 and words[i] in ("builtin", "command"):
        i += 1
    return i if i < len(words) and words[i] in CD_HEADS else None


def _cd_target(words: list, at: int):
    """The directory word a cd / pushd at `at` changes to ("~" for none), or None for one this
    reading cannot know (popd, `cd -`, `pushd +N`)."""
    ops, it = [], iter(words[at + 1:])
    for w in it:
        if w == "--":
            ops.extend(it)
        elif re.fullmatch(r"-[LPe@]+", w):
            continue
        else:
            ops.append(w)
    if words[at] == "popd" or (ops and re.fullmatch(r"-|[+-]\d+", ops[0])):
        return None
    return ops[0] if ops else "~"


def _cd_dirs(segments: list, cwd: str) -> list:
    """The directories a command's paths may be read from, all together: the call's, and each `cd` /
    `pushd` target, read both from the directory the chain before it leaves (`cd ~ && cd .claude`)
    and from the call's. A bare `cd` is $HOME. A word whose own directory _chain cannot tell (a
    payload a shell runs, a function's body, a re-read word) is read from all of these."""
    out, here, seen = {cwd: None}, cwd, {}
    for words, _ in segments:
        at = _cd_at(words)
        if at is None:
            continue
        target = _cd_target(words, at)
        if target is None:
            continue
        for base in (here, cwd):  # each (target, directory) resolved once: a padded `cd .` costs one
            if (target, base) not in seen:
                seen[(target, base)] = _resolve(target, base)
            out[seen[(target, base)]] = None
        here = seen[(target, here)]
    return list(out)


def _env_chdir(words: list):
    """The directory word an `env -C` / `--chdir` among a command's leading words runs it in, or None."""
    for i, w in enumerate(words[:8]):
        if os.path.basename(w) != "env":
            continue
        it = iter(words[i + 1:])
        for o in it:
            m = re.fullmatch(r"-[i0v]*C(.*)", o, re.S)
            if m:
                return m.group(1) or next(it, None)
            if o.startswith("--ch") and "--chdir".startswith(o.split("=", 1)[0]):
                return o.split("=", 1)[1] if "=" in o else next(it, None)
            if o in ("-u", "--unset", "-S", "--split-string"):
                next(it, None)
            elif not o.startswith("-") or o == "--":
                break
    return None


def _chain(script, cwd: str) -> dict:
    """Where each command of `script` runs: {id(SimpleCommand), or ("r", id(a compound's first
    redirection)): [directories]}, read along the script's own control flow. A `cd` / `pushd` (or
    `builtin cd`, `command cd`) into a directory that is there and enterable moves the commands its
    success reaches (`cd ~/.claude && cd /tmp && echo x > f` writes /tmp/f); one that may fail keeps
    the directory before it for the commands its failure reaches (`||`, a later `;`); a subshell's,
    a pipeline stage's, a background list's `cd` stays inside it; a branch or a loop body may run
    or not; a function's body may run anywhere after it (its commands are left to _cd_dirs, and its
    `cd` moves every command after it as may-be). A `cd` whose directory cannot be known (`cd -`,
    popd, a computed word, a CDPATH that is set) may land in any directory the chain has seen, or in
    each CDPATH entry. `env -C <dir>` runs its own command in <dir>. Payloads a shell runs and
    substitutions are not mapped (_cd_dirs reads them)."""
    out, env, seen = {}, dict(os.environ), {cwd: None}

    def record(key, dirs):
        out.setdefault(key, {}).update(dict.fromkeys(dirs))

    def cd(words, at, d):  # [(directory, succeeded)] a cd at `at` run from `d` may leave
        target = _cd_target(words, at)
        pre = dict(a.split("=", 1) for a in words[:at] if ASSIGNMENT.match(a))
        cdpath = pre.get("CDPATH", env.get("CDPATH", ""))
        if target is None or "${" in target:
            new = list(seen) + ([_resolve(target, d)] if target else [])
            return [(n, True) for n in new] + [(d, False)]
        bases = [d]
        if cdpath and not re.match(r"(?:/|~|\.\.?(?:/|\Z))", target):
            bases += [_resolve(e or ".", d) for e in cdpath.split(":")] + list(seen)
        new = list(dict.fromkeys(_resolve(target, b) for b in bases))
        certain = len(new) == 1 and os.path.isdir(new[0]) and os.access(new[0], os.X_OK)
        return [(n, True) for n in new] + ([] if certain else [(d, False)])

    def simple(cmd, dirs):
        for a in cmd.assignments if not cmd.words else ():
            env.pop(a.name, None) if a.static_value() is None else env.update({a.name: a.static_value()})
        words = [_text(w, env) for w in [a.word for a in cmd.assignments] + list(cmd.words)]
        chdir = _env_chdir(words)
        record(id(cmd), [_resolve(chdir, d) for d in dirs] if chdir else dirs)
        if words and words[0] in EXPORTS:
            for w in words[1:]:
                if ASSIGNMENT.match(w) and "${" not in w:
                    env.update([w.split("=", 1)])
        at = _cd_at(words)
        if at is None:
            return [(d, ok) for d in dirs for ok in (True, False)]
        return [r for d in dirs for r in cd(words, at, d)]

    def stage(cmd, dirs):  # [(directory, succeeded)] after one pipeline stage run from `dirs`
        if isinstance(cmd, shell_parse.SimpleCommand):
            return simple(cmd, dirs)
        if cmd.redirects:
            record(("r", id(cmd.redirects[0])), dirs)
        end = list(dirs)
        if cmd.kind in ("subshell", "coproc"):
            for body in cmd.body:
                script_(body, dirs)
        elif cmd.kind == "function":
            for body in cmd.body:
                end += script_(body, list(dirs) + list(seen), mapped=False)
        elif cmd.kind == "group":
            for body in cmd.body:
                end = script_(body, end)
        else:  # if, while, until, for, select, case, cond, arith: each body may run, a loop's again
            here, again = list(dirs), cmd.kind in ("while", "until", "for", "select")
            while True:
                before = here
                for body in cmd.body:
                    here = list(dict.fromkeys(here + script_(body, here)))
                if not again or here == before:  # a loop's next turn starts where its body left
                    break
                again = False
            end = here
        return [(d, ok) for d in dict.fromkeys(end) for ok in (True, False)]

    def script_(sc, dirs, mapped=True):  # the directories `sc` run from `dirs` may leave
        nonlocal out
        saved = out if not mapped else None
        if not mapped:
            out = {}
        here = list(dirs)
        states, op = None, None  # an and-or list's (directory, last status) paths
        for pl, sep in sc.items:
            if states is None:
                start, states = here, [(d, ok) for d in here for ok in (True,)]
                runs, passes = states, []
            else:
                runs = [s for s in states if s[1] == (op == "&&")]
                passes = [s for s in states if s[1] != (op == "&&")]
            dirs_in = list(dict.fromkeys(d for d, _ in runs))
            if not dirs_in:
                result = []
            elif len(pl.stages) > 1:
                for st in pl.stages:
                    stage(st, dirs_in)
                result = [(d, ok) for d in dirs_in for ok in (True, False)]
            else:
                result = stage(pl.stages[0], dirs_in)
                if pl.negated:
                    result = [(d, ok) for d, _ in result for ok in (True, False)]
            for d, _ in result:
                seen[d] = None
            states = list(dict.fromkeys(passes + result))
            if sep in ("&&", "||"):
                op = sep
                continue
            here = start if sep == "&" else list(dict.fromkeys(d for d, _ in states)) or start
            states, op = None, None
        if states is not None:
            here = list(dict.fromkeys(d for d, _ in states)) or here
        if not mapped:
            out = saved
        return here

    script_(script, [cwd])
    return {k: list(v) for k, v in out.items()}


def _chained(chain: dict, cmd, fallback: list) -> list:
    """The directories `cmd` (a Site's SimpleCommand) runs in, by _chain, else `fallback`."""
    if cmd is None:
        return fallback
    dirs = chain.get(id(cmd))
    if dirs is None and not cmd.words and not cmd.assignments and cmd.redirects:
        dirs = chain.get(("r", id(cmd.redirects[0])))
    return dirs or fallback


def _argv(words: list) -> list:
    """A command's words past the assignments before it (an operand spelled NAME=VALUE stays)."""
    i = 0
    while i < len(words) and ASSIGNMENT.match(words[i]):
        i += 1
    return words[i:]


def _written_by(words: list, written: list, awk: bool = False, interpreter: bool = False,
               members: bool = True) -> list:
    """The words of one simple command that it writes: the paths it writes (`written`), and
    for a reader nothing else (READ_ONLY, git's readers, sed without -i, -f or e; tar -c / -t,
    its -f archive alone; with `awk`, awk whose program has no > | or system(); with `interpreter`,
    an interpreter provably read-only, _interpreter_reads); for cp its destination and each
    source's name inside it; for any other command every word (tee, dd, sed -i, perl -i, mv, rm,
    ...), with awk's quoted strings, the text after each `w` of a sed script this reading cannot
    follow, and mv's, ln's and install's destination and each source's name inside it; for tar
    that is no reader, also the settings files it may extract (_tar_extracts) unless `members` is
    False (writes_settings_file: only a word the command spells names a settings file there)."""
    plain = _argv(words)
    if not plain:
        return list(written)
    head = os.path.basename(plain[0])
    if head == "sed":
        files = _sed(plain)
        return list(written) + (files if files is not None else words + _sed_w_words(plain))
    if head in AWKS:
        program = _awk(plain)
        if awk and program is not None and not AWK_OUTPUT.search(program):
            return list(written)
        return list(written) + words + AWK_STRING.findall(program or " ".join(plain[1:]))
    if head == "tar":
        files = _tar(plain)
        return list(written) + (files if files is not None else words + (_tar_extracts(plain) if members else []))
    if _read_only(words) or (interpreter and INTERPRETER.match(head) and _interpreter_reads(plain)):
        return list(written)
    if head == "cp":
        return list(written) + [w for w, _ in _operands(plain, False)]
    return list(written) + words + ([w for w, _ in _operands(plain, head == "mv")]
                                    if head in ("mv", "ln", "install") else [])


def writes_settings_file(command: str) -> bool:
    """True when `command` writes a settings*.json file, in any directory: one of the words it
    writes (_written_by; an interpreter whose -c text shows no write reads) names one."""
    return any(NAMES_SETTINGS.search(w) for words, written in _commands(command, "code")
               for w in _written_by(words, written, awk=True, interpreter=True, members=False))


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


OPERAND_VALUES = {"cp": "S", "mv": "S", "ln": "S", "install": "mogS"}  # short options taking a value


def _operands(plain: list, moves: bool) -> list:
    """cp / mv / ln / install: (word, dirs_too) for the destination, each source's name inside it,
    and, for mv, each source (moved away); cp's sources are only read. The destination is a -t
    (spaced, attached, or ending a cluster: `-vt DIR`, `-tDIR`), a --target-directory or any
    abbreviation of it (`--target=DIR`, `--target DIR`), else the last operand."""
    sources, dest, it = [], None, iter(plain[1:])
    values = OPERAND_VALUES.get(os.path.basename(plain[0]), "S")
    for w in it:
        name, eq, value = w.partition("=")
        if w == "--":
            sources.extend(it)
        elif w.startswith("--t") and "--target-directory".startswith(name):
            dest = value if eq else next(it, None)
        elif w.startswith("--su") and "--suffix".startswith(name) and not eq:
            next(it, None)
        elif w.startswith("-") and not w.startswith("--") and len(w) > 1:
            for k, ch in enumerate(w[1:], 1):
                if ch == "t":
                    dest = w[k + 1:] or next(it, None)
                    break
                if ch in values:
                    if not w[k + 1:]:
                        next(it, None)
                    break
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
    and mv's destination, and mv's sources. A path is read from the directory the command runs in
    (_chain; else from the call's directory and every `cd`'s, _cd_dirs).
    Each directory, and each word with its kind, is read once: a command padded with repeated
    `cd .` costs what its distinct words cost, not their count times its segments'."""
    script, sites = shell_parse.parse(command), []
    segments = list(_commands(script, "shell", sites=sites))
    git_dirs = [d for w, _ in segments for d in _git_dirs(w, cwd)]
    every_dir, chain = list(dict.fromkeys(_cd_dirs(segments, cwd) + git_dirs)), _chain(script, cwd)
    out, seen, home = [], set(), _settings_files()
    for (words, written), cmd in zip(segments, sites):
        plain = _argv(words)
        if not plain:
            continue
        dirs = tuple(dict.fromkeys(_chained(chain, cmd, every_dir) + git_dirs))
        head = os.path.basename(plain[0])
        interpreter = INTERPRETER.match(head) and not any(re.fullmatch(r"-[A-Za-z]*i.*", w) for w in plain[1:])
        message, moves = _message(plain), head in ("cp", "mv")
        named = [(w, head in ("rm", "rmdir", "rsync")) for w in
                 (written if (interpreter or message or moves) else _written_by(words, written, awk=True))]
        named += _operands(plain, head == "mv") if moves else []
        for word, dirs_too in named:
            if (word, dirs_too, dirs) not in seen:
                seen.add((word, dirs_too, dirs))
                out.extend(_named_settings(word, list(dirs), dirs_too, home))
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


EXPORTS = ("export", "declare", "typeset", "local", "readonly")


def _in_home(paths: list, settings: set) -> bool:
    """Whether one of the resolved `paths` is the harness home (or Claude Code's config dir), or
    under it."""
    homes = {os.path.dirname(f) for f in settings}
    return any(p == h or p.startswith(h + os.sep) for p in paths for h in homes)


def _foreign_config(git, ran_in: list, settings: set, exported: bool) -> bool:
    """Whether the command, not the repository and the owner, chooses the config this git call
    reads: an assignment before it (or an earlier export or assignment) of HOME, XDG_CONFIG_HOME,
    GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM or GIT_CONFIG_NOSYSTEM, or a GIT_DIR= / --git-dir naming
    a repository other than the harness home's or the one in the directory git runs in (GIT_DIR=,
    GIT_COMMON_DIR= and --git-dir are its `gitdirs`)."""
    if git.source or exported:
        return True
    for g in git.gitdirs:
        for r in ran_in:
            d = _resolve(g, r) if g else r
            if not (_in_home([d], settings) or d in (r, os.path.join(r, ".git"))):
                return True
    return False


def _unknown_exports(segments: list, shared: list) -> list:
    """NAME=UNKNOWN for each variable GIT_CARRIED names that the command exports (export NAME,
    declare -x / typeset -x / local -x NAME, or any NAME under set -a / set -o allexport) while
    its value is not read here: no assignment of it earlier in the command, or it is named
    elsewhere too (printf -v, read, mapfile, declare -n r=NAME, $NAME, ...)."""
    def exporting(w):
        head = os.path.basename(w[0]) if w else ""
        return head == "export" or (head in ("declare", "typeset", "local")
                                    and any(re.fullmatch(r"-[A-Za-z]*x[A-Za-z]*", x) for x in w[1:]))
    allexport = any(w and w[0] == "set" and any(re.fullmatch(r"-[A-Za-z]*a[A-Za-z]*", x) or x == "allexport"
                                                for x in w[1:]) for w, _ in segments)
    names = {x for w, _ in segments if allexport or exporting(w) for x in w[1:] if re.fullmatch(r"[A-Za-z_]\w*", x)}
    out = []
    for name in sorted(n for n in names if GIT_CARRIED.match(n)):
        mention = re.compile(r"(?<![\w])%s(?![\w])" % name)
        static = any(x.startswith(name + "=") for x in shared)
        other = any(mention.search(x) and not x.startswith(name + "=") and not (x == name and exporting(w))
                    for w, _ in segments for x in w)
        if not static or other:
            out.append(name + "=" + UNKNOWN)
    return out


def _foreign_tree(git, cds: list, settings: set) -> bool:
    """Whether, from some directory the command runs git in, its work tree (--work-tree,
    GIT_WORK_TREE, core.worktree) is in the harness home while its repository (GIT_DIR / --git-dir,
    else where -C leaves it) is not: the command, not the home, chooses that repository's config."""
    for base in dict.fromkeys(cds):
        here, trees = base, []
        for opt, d in git.dirs:
            if opt == "-C":
                here = _resolve(d, here) if d else here
            else:
                trees.append(d)
        repos = [_resolve(g, here) for g in git.gitdirs if g] or [here]
        if (UNKNOWN in trees or _in_home([_resolve(t, here) for t in trees], settings)) and not all(_in_home([r], settings) for r in repos):
            return True
    return False


def _shared_assignments(segments: list) -> list:
    """The NAME=value words that reach every later command, or a shell's commands: an export
    (export, declare, ...), a command of assignments alone, and the assignments before a shell or
    other interpreter (`HOME=/tmp/x bash -c '...'`), past env and the plain wrappers."""
    out = []
    for w, _ in segments:
        if not w:
            continue
        if all(ASSIGNMENT.match(x) for x in w) or os.path.basename(w[0]) in EXPORTS:
            out += [x for x in w if ASSIGNMENT.match(x)]
            continue
        pre = []
        for x in w:
            if ASSIGNMENT.match(x):
                pre.append(x)
            elif not (os.path.basename(x) in GIT_WRAPPERS or x.startswith("-") or x.isdigit()):
                if INTERPRETER.match(os.path.basename(x)):
                    out += pre
                break
    return out


def check_bash(command: str, cwd: str, data: dict | None = None) -> int:
    if "disableAllHooks" in command and writes_settings_file(command):
        return refuse("this Bash command writes disableAllHooks into a settings file, which would switch every "
                      "hook off")
    script, sites = shell_parse.parse(command), []
    if script.error is not None and TYPED.search(command) and NESTED.search(command):  # text the parser cannot read
        return refuse("this Bash command types /harness into a Claude Code session, where it would reach "
                      "the switch as a prompt")
    settings, segments = _settings_files(), list(_commands(script, "all", every_word=True, sites=sites))
    every_dir, checked = _cd_dirs(segments, cwd), set()  # the call's directory and each `cd`'s, chains read through
    why = _executions(script, command, every_dir, _switch_identity()) if script.error is None else None
    if why is not None:
        return refuse("this Bash command " + why + ("" if "session" not in why else
                                                    ", where it would reach the switch as a prompt"))
    chain = _chain(script, cwd)  # where each command runs, read along the chain
    shared = _shared_assignments(segments)  # an export, a lone assignment, or one before a shell
    shared += _unknown_exports(segments, shared)  # exported with a value set by printf -v, read, ...
    exported = any(GIT_CONFIG_SOURCE.match(x) for x in shared)
    carried = [x for x in shared if x.split("=", 1)[0] in GIT_TREE_ENV or GIT_TRACE_ENV.match(x.split("=", 1)[0])]
    less_env = bool(LESS_ENV.search(command))
    for (words, written), cmd in zip(segments, sites):
        dirs = _chained(chain, cmd, every_dir)
        git, bases, foreign = _git(words, carried, less_env), dirs, False
        if git is not None:
            written = list(written) + git.traces  # GIT_TRACE*=<absolute path> appends git's trace there
            bases = list(dict.fromkeys(dirs + [g for d in dirs for g in _git_dirs(words, d)]))
            ran_in = [(_git_dirs(words, d) or [d])[-1] for d in dirs]  # from each directory it runs in
            editor = not (git.sub is not None and words[git.sub] in GIT_EDITOR_FREE)
            trees = [d for opt, d in git.dirs if opt == "--work-tree"]
            in_home = UNKNOWN in trees or _in_home(ran_in + [_resolve(d, r) for d in trees for r in ran_in]
                                                    + [_resolve(g, r) for g in git.gitdirs if g for r in ran_in], settings)
            if git.program and _in_home(ran_in, settings):
                return refuse("this Bash command runs git in the harness home with a -c or --config-env that "
                              "names a program (alias.*, core.hooksPath, core.fsmonitor, core.pager, ...), a "
                              "`!` value, or an --exec-path=<dir>, which can rewrite the home's settings or the "
                              "switch's state")
            if (git.env or _env_program(shared, editor, less_env)) and in_home:
                return refuse("this Bash command runs git in the harness home with an environment that names a "
                              "program or config (GIT_CONFIG_PARAMETERS, GIT_CONFIG_KEY_<n>, GIT_EXTERNAL_DIFF, "
                              "GIT_SSH_COMMAND, GIT_PAGER, PAGER, GIT_EDITOR, EDITOR, ...), which can rewrite the "
                              "home's settings or the switch's state")
            if git.sub is not None and words[git.sub] == "grep" and _in_home(ran_in, settings) and any(
                    _grep_opens_program(w, less_env) for w in words[git.sub + 1:]):
                return refuse("this Bash command runs git grep in the harness home with -O<cmd> / "
                              "--open-files-in-pager=<cmd>, a program run there, which can rewrite the home's "
                              "settings or the switch's state")
            if _foreign_config(git, ran_in, settings, exported) or _foreign_tree(git, dirs, settings):
                if in_home:
                    return refuse("this Bash command runs git in the harness home with config the command chooses "
                                  "(HOME, XDG_CONFIG_HOME, GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM, GIT_DIR, "
                                  "GIT_COMMON_DIR or a --git-dir of another repository, or the home as the work tree "
                                  "of another repository), whose diff.external, alias, hook "
                                  "or pager can rewrite the home's settings or the switch's state")
                if git.sub is not None and _in_home([_resolve(w.split("=", 1)[-1] if w.startswith("-") else w, r)
                                                     for w in words[git.sub + 1:] for r in ran_in], settings):
                    foreign = True  # git reads a harness-home path under config the command chooses
        for word in words if cmd is None and script.error is not None else ():  # text the parser cannot read
            token = word.split("=", 1)[-1]
            if os.path.basename(token.rstrip("/")) in SWITCH_PROGRAMS and not _read_only(words):
                return refuse("this Bash command runs the switch (%s)" % os.path.basename(token))
        if _writes_switch(words, written):
            return refuse("this Bash command writes the switch program")
        named = list(written) + words if foreign else _written_by(words, written)  # only a reader is relaxed
        for word in dict.fromkeys(named):  # the home's files
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


PROSE = (".md", ".txt", ".rst")  # a file kind no shell or interpreter runs: naming the state there is prose
STATE_WRITE = re.compile(  # a line of prose that writes, moves or removes what it names, or keeps it for a write
    r"\b(?:rm|rmdir|touch|mkdir|mv|cp|ln|tee|dd|install|truncate|chmod|chown|unlink|shred|rsync|cd|pushd"
    r"|mknod|mkfifo|exec|eval|subprocess|shutil|pathlib|os\.\w+|fs\.\w+)\b|\bsed\b.*\s-[A-Za-z]*i"
    r"|\bperl\b.*\s-[A-Za-z]*i|[A-Za-z_][A-Za-z0-9_]*=|(?<![-=])>(?!=)|\b(?:open|write\w*|unlink|remove\w*"
    r"|rename|replace|mkdirs?|makedirs|rmtree|copy\w*|move|symlink\w*|link|touch|appendFile\w*|writeFile\w*"
    r"|system|Path)\s*\(")
QUOTE_MARK = re.compile(r"\A\s*(?:>\s*)+")  # a Markdown blockquote's markers, no redirect


def _names_state(names: tuple, text: str) -> bool:
    """Whether a written file's text names the switch's state in a way that may change it: any
    mention in a file of any kind but prose (.md, .txt, .rst; by every one of `names`, the path as
    written and as resolved, so a link named x.sh is no prose); in prose, a line that names it and
    writes (a writing command, a `>` redirect, sed -i, a `cd` into it, an assignment of it, a
    write call)."""
    if harness_switch.DIR_NAME not in text:
        return False
    if not all(n.lower().endswith(PROSE) for n in names):
        return True
    return any(harness_switch.DIR_NAME in line and STATE_WRITE.search(QUOTE_MARK.sub("", line))
               for line in text.splitlines())


class _Pairs(dict):
    """A JSON object that keeps every (key, value) pair, a repeated key's too."""

    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs


def _truthy(value) -> bool:
    """JavaScript's truth of a JSON value: false, null, 0 and "" are false, all else true."""
    return not (value is None or value is False or value == "" or
                (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0))


def _disable_values(text: str):
    """Every value the top-level object of `text` gives disableAllHooks (a repeated key's each);
    None when the text is no JSON object the CLI would load."""
    try:
        doc = json.loads(text.lstrip("\ufeff"), object_pairs_hook=_Pairs, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(doc, _Pairs):
        return None
    return [json.dumps(v, sort_keys=True) for k, v in doc.pairs if k == "disableAllHooks"]


def _sets_disable_all_hooks(tool: str, ti: dict, path: str, text: str) -> bool:
    """Whether a call on a settings*.json leaves disableAllHooks truthy: a Write whose document
    holds a truthy value; an Edit or MultiEdit whose result holds one it did not hold before. A
    document that cannot be computed or read as JSON counts when the call's text names the key."""
    before = None
    if tool in ("Edit", "MultiEdit"):
        try:
            with open(path, encoding="utf-8") as fh:
                before = fh.read()
        except (FileNotFoundError, NotADirectoryError):
            before = None
        except (OSError, UnicodeDecodeError):
            before = False
    after = _edit_result(tool, ti, before) if tool in ("Write", "Edit", "MultiEdit") else None
    values = _disable_values(after) if after is not None else None
    if values is None:
        return "disableAllHooks" in text
    if not any(_truthy(json.loads(v)) for v in values):
        return False
    if tool == "Write" or "disableAllHooks" in text:
        return True
    old = _disable_values(before) if isinstance(before, str) else None
    return old != values


def check_write(tool: str, ti: dict, cwd: str, data: dict | None = None) -> int:
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    if not isinstance(raw, str) or not raw:
        return 0
    path = _resolve(raw, cwd)
    if _in_state(path):
        return refuse("this %s writes the switch's state (%s)" % (tool, raw))
    text = _new_text(tool, ti)
    name = os.path.basename(path)
    if SETTINGS_ANY.fullmatch(name) and _sets_disable_all_hooks(tool, ti, path, text):
        return refuse("this %s sets disableAllHooks in %s, which would switch every hook off" % (tool, raw))
    if path in _settings_files() and not _allow_settings(cwd):
        return refuse("this %s writes the harness home's %s" % (tool, name))
    named = _named_settings(raw, [cwd])
    if named:
        before = _current(named[0])
        change = _settings_change(_held(named[0]), _edit_result(tool, ti, before))
        if change and not _granted(tool, ti, data or {}):
            return _refuse_settings(tool, change, raw)
    if _names_state((name, os.path.basename(raw)), text) and not _in_harness_checkout(path):
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
