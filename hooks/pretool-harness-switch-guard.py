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
                        or writing it; a command whose words name it passes only when it provably
                        reads it alone (_harmless_read: sed -n, shellcheck, bash -n, ...); writing the switch's
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
                        but prose (.md, .txt, .rst), where the whole document must be plain
                        (_plain_line: no line holds shell syntax or a quote or starts with a word
                        that runs) and each line naming it a bare directory mention (_dir_mention)
  CronCreate / ScheduleWakeup / SendMessage
                        a prompt or message the switch's own parser (scripts/harness-switch
                        parse_prompt) takes for the /harness command, typed or in the command-name
                        tag form (a scheduled prompt reaches UserPromptSubmit as if typed); a prompt
                        that only mentions /harness passes; fails closed on any /harness when the
                        parser cannot be loaded

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
import shutil  # noqa: E402

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
AWK_OUTPUT = re.compile(r"[>|]|\bsystem\b|@\s*[A-Za-z_]")  # print > file, print | command, system(), and
# any gawk `@name`: the @include / @load / @namespace directives (`@include "inplace"` is -i inplace) and indirect
# calls (`f="sys" "tem"; @f(...)` calls system() without spelling it): an awk program that writes, loads another
# program or may call one; a harmless `@` use such as "@ind_str_asc" is refused too (fail-closed)
AWK_ENV = re.compile(r"\b(?:AWKPATH|AWKLIBPATH|GAWK_PERSIST_FILE)\b")  # what awk loads, a file gawk writes: named
# anywhere in the command (before awk, after env, exported, declared), they make every awk in it no reader
AWK_NAME_SAFE = frozenset({  # the commands that cannot change which program the name `awk` runs: with only these
    "cat", "grep", "egrep", "fgrep", "head", "tail", "wc", "ls", "echo", "printf", "sed", "test", "[", "true",
    "false", ":", "cd", "pwd"} | set(AWKS))  # (printf without -v, sed that only reads, awk proven a reader), any
AWK_NAME_READERS = READ_ONLY - {"find", "less", "more", "printf"}  # other reader _read_only passes (nl, cut, ...), no
# assignment word (POSIXLY_CORRECT=1 before a command aside), no compound command, no arithmetic, no `$` expansion
# outside awk's own words, and no output redirection but to /dev/null or onto a numbered fd (_awk_trusted)
AWK_OUT_OPS = (">", ">>", ">|", "&>", "&>>", "<>", ">&")
AWK_PARAM_PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!_-]")  # $name, ${name}, $1, $@: no subscript or
# operator (`${a[PATH=1]}`, `${PATH:=x}`, `${!x}` can assign or reach any name)
AWK_UNSAFE = frozenset("{}*?[]$`~!")  # unquoted, a character the shell may expand (brace, glob, $, `, ~, !)
AWK_LOADS = re.compile(r"@\s*(?:include|load|namespace)\b")  # gawk's directives that load another file
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
                "xargs", "sudo", "doas", "flock", "chrt", "taskset", "unbuffer")  # its inner git is judged as git
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
GIT_WRITE_ENV = re.compile(  # a variable naming a file or directory git creates and writes, whatever it runs
    r"GIT_(?:INDEX_FILE|OBJECT_DIRECTORY|ALTERNATE_OBJECT_DIRECTORIES)\Z")
GIT_CARRIED = re.compile(  # a variable that hands git a program, config or repository: its value matters
    r"(?:GIT_(?:EXTERNAL_DIFF|SSH_COMMAND|SSH|ASKPASS|PAGER|EDITOR|SEQUENCE_EDITOR|EXEC_PATH|DIR|COMMON_DIR"
    r"|WORK_TREE|TEMPLATE_DIR|CONFIG\w*|TRACE\w*|INDEX_FILE|OBJECT_DIRECTORY|ALTERNATE_OBJECT_DIRECTORIES)|SSH_ASKPASS|PAGER|EDITOR|VISUAL|HOME|XDG_CONFIG_HOME)\Z")
UNKNOWN = "/?unknown-value?"  # the value of a variable the command sets in a way not read here
LESS_ENV = re.compile(r"\bLESS\w*")  # less's own environment: LESS, LESSOPEN, LESSKEY, ...
GIT_CONFIG_SOURCE = re.compile(  # where git reads its global and system config from (GIT_TREE_ENV aside)
    r"(?:HOME|XDG_CONFIG_HOME|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM)=")
GIT_WRITING_LONG = ("output", "ext-diff", "textconv", "filters")  # a reader's options that write or run a program
GIT_ABBREVIATING = {"grep": ("textconv", "open-files-in-pager"), "cat-file": ("textconv", "filters"),
                    "range-diff": ("output", "ext-diff", "textconv")}  # readers whose options git abbreviates
GIT_HARMLESS_LONG = ("text",)  # a reader's own option spelled as a prefix of one of those
GIT_GREP_ARG_SHORTS = "efABCm"  # git grep's short options whose value is the rest of the word
GIT_CONFIG_VALUE_OPTS = ("-f", "--file", "--blob", "--type", "--default", "--comment", "--value", "--url")
GIT_CONFIG_LONG = (  # git config's long options (old flags and the subcommands' options); git takes a unique prefix
    "global", "system", "local", "worktree", "file", "blob", "get", "get-all", "get-regexp", "get-urlmatch",
    "replace-all", "add", "unset", "unset-all", "rename-section", "remove-section", "list", "fixed-value",
    "edit", "get-color", "get-colorbool", "type", "no-type", "bool", "int", "bool-or-int", "path",
    "expiry-date", "null", "name-only", "includes", "no-includes", "show-origin", "show-scope", "show-names",
    "default", "comment", "value", "url", "all", "regexp", "append")
GIT_CONFIG_SHORT_VALUE = "ft"  # -f <file>, -t <type>; -l, -e, -z take none
GIT_INIT_LONG = ("template", "bare", "quiet", "shared", "separate-git-dir", "initial-branch", "object-format",
                 "ref-format")  # git init's long options; git takes a unique prefix
GIT_INIT_VALUE = ("separate-git-dir", "initial-branch", "object-format", "ref-format", "template")
GIT_CONFIG_NO_SET = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool",
                     "--list", "-l", "--unset", "--unset-all", "--remove-section", "--blob", "-e", "--edit",
                     "get", "list", "unset", "remove-section", "edit")  # git config forms that set no value
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
SESSIONLESS = ("--version", "-v", "--help", "-h", "doctor", "mcp")  # claude's forms that start no session
CLAUDE_LOOKUPS = (("which",), ("which", "-a"), ("command", "-v"), ("command", "-V"), ("type",), ("type", "-a"),
                  ("type", "-t"), ("type", "-p"), ("type", "-P"))  # find claude on PATH; run nothing
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


PROOF_READERS = frozenset({"cat", "head", "tail", "wc", "ls", "stat", "file", "md5sum", "sha1sum", "sha256sum",
                           "sha512sum", "cksum", "diff", "cmp", "nl", "od", "grep", "egrep", "fgrep",
                           "shellcheck"})  # no interpreter: a python -m module, pylint, flake8, ruff or cp runs or
# plants code (cwd first on sys.path, cwd rc files, a copy into a PATH dir or as <module>.py)
RG_LONG = frozenset(("after-context", "before-context", "binary", "byte-offset", "case-sensitive", "color", "colors",
                     "column", "context", "count", "count-matches", "crlf", "files", "files-with-matches",
                     "files-without-match", "fixed-strings", "follow", "glob", "heading", "hidden", "iglob",
                     "ignore-case", "invert-match", "line-number", "line-regexp", "max-columns", "max-count",
                     "max-depth", "multiline", "multiline-dotall", "no-filename", "no-heading", "no-ignore",
                     "no-line-number", "no-messages", "null", "only-matching", "passthru", "quiet", "regexp",
                     "smart-case", "sort", "sortr", "stats", "text", "trim", "type", "type-not", "unrestricted",
                     "with-filename", "word-regexp", "vimgrep", "json", "fixed-strings"))  # rg's long options
# that run nothing: any other, an abbreviation of --pre / --pre-glob / --hostname-bin / --hyperlink-format
# included, is no proof
GIT_PROOF_BANNED = ("--ext-diff", "--textconv", "--open-files-in-pager", "--output", "--output-directory", "--exec",
                    "--upload-pack", "--receive-pack", "--config-env", "--paginate")  # or an abbreviation of one
PROOF_BANNED = frozenset({"export", "declare", "typeset", "local", "readonly", "set", "alias", "read", "mapfile",
                          "readarray", "enable"}) | TEXT_RUNNERS  # set or export a variable, or run text
PROOF_SINKS = ("/dev/null", "/dev/stdout", "/dev/stderr")


def _dynamic(word, env: dict) -> bool:
    """Whether the shell computes a word (an expansion `env` cannot read, a substitution, a glob, a brace)."""
    return any(p.kind != "lit" and not (p.kind == "param" and p.text in env) for p in word.parts)


def _proof_reader(res, env: dict) -> bool:
    """Whether a resolved command only reads its operands: a reader on the allow-list, with no option
    that runs a program or writes a file."""
    name = res.name
    if name is None or res.payload is not None or res.assignments:
        return False
    if any(w[0] in TEXT_RUNNERS for w in res.wrappers):
        return False
    args = [_text(w, env) for w in res.args]
    plain = [name] + args
    if name in PROOF_READERS:
        return True
    if name == "rg":
        for a in args:
            if a == "--":
                break
            if a.startswith("--"):
                if a[2:].split("=", 1)[0] not in RG_LONG:
                    return False
            elif a.startswith("-") and not re.fullmatch(r"-[A-Za-y0-9]+", a):
                return False  # -z runs decompressors
        return True
    if name in ("less", "more"):
        return all(re.fullmatch(r"-[A-Za-z]+", a) and not re.search("[oOk]", a) or not a.startswith(("-", "+"))
                   for a in args)
    if name == "sed":
        return _sed(plain) == []
    if name in AWKS:
        program = _awk(plain)  # None for -f / --file / -i / --include / -l / --load / -E / --exec
        return (program is not None and not AWK_OUTPUT.search(program) and "getline" not in program
                and not AWK_LOADS.search(program))
    if name == "git":
        return _read_only(plain) and not any(
            a.startswith(("-O", "-c")) or a.startswith("--") and len(a.split("=", 1)[0]) > 3 and any(
                b.startswith(a.split("=", 1)[0]) for b in GIT_PROOF_BANNED) for a in args)
    kind = _kind(name)
    if kind == "shell":
        return name in ("bash", "sh") and len(args) == 2 and args[0] == "-n" and not args[1].startswith(("-", "+"))
    return False


def _harmless_nested(script) -> bool:
    """Whether a command holding both /harness text and a nested `claude` provably starts no
    session that could read the text: every simple command (substitutions and function bodies
    included) is, with no assignment, wrapper or path-named command word, either `claude` with a
    sessionless form alone (--version, -v, --help, -h, doctor, `mcp list` / `mcp get <name>`),
    which / command -v|-V / type of plain names, echo, printf without -v, or a proven reader
    (_proof_reader); and nothing writes a file but /dev/null, /dev/stdout, /dev/stderr. Anything
    else (interpreter code, a text runner, an unknown runner, a copy or link of the binary, git with
    -c or an alias, sed's e) keeps the parent's refusal."""
    env = dict(os.environ)
    for t in shell_parse.write_targets(script):
        if t.word is None or t.path not in PROOF_SINKS:
            return False
    for site in shell_parse.walk(script):
        cmd = site.cmd
        if site.dynamic or cmd.assignments or not cmd.words:
            return False
        res = shell_parse.resolve(cmd)
        if res.unresolved or res.assignments or res.wrappers or res.payload is not None or res.head is None:
            return False
        head = res.head.value()
        if head is None or "/" in head or res.head is not cmd.words[0]:
            return False
        if head == "claude":
            args = [w.value() for w in res.args]
            if any(a is None for a in args) or not args:
                return False
            if not (len(args) == 1 and args[0] in SESSIONLESS and args[0] != "mcp"
                    or len(args) == 2 and args == ["mcp", "list"]
                    or len(args) == 3 and args[:2] == ["mcp", "get"] and not args[2].startswith("-")):
                return False
            continue
        words = [w.value() for w in cmd.words]
        if all(w is not None for w in words) and any(
                tuple(words[:len(k)]) == k and words[len(k):] and all(
                    not w.startswith("-") and "/" not in w for w in words[len(k):]) for k in CLAUDE_LOOKUPS):
            continue
        if head == "echo" or head == "printf" and not any(
                (w.value() or "-v").startswith("-v") for w in res.args[:1]):
            continue
        if res.name == head and _proof_reader(res, env):
            continue
        return False
    return True


def _harmless_read(script, dirs: list, ident: list) -> bool:
    """Whether a command that names the switch program only reads it: every simple command a word of
    which names it (by text, real path, inode or content), names a file the command writes, or is
    computed, is a reader on an allow-list (_proof_reader), as is every pipeline stage fed by such a
    command; no command sets or exports a variable, runs text (xargs, eval, source, exec, find -exec,
    ...), runs an interpreter or shell other than `bash -n F` / `sh -n F`, or writes a file (a
    redirect or tee to anything but /dev/null, /dev/stdout, /dev/stderr), so no copy is made."""
    env = dict(os.environ)
    written = []
    for t in shell_parse.write_targets(script):
        if t.word is None or t.path not in PROOF_SINKS:
            return False  # a reader writes nothing but /dev/null and its own stdout / stderr

    def mentions(text: str) -> bool:
        flat = re.sub(r"[\\'\"]", "", text)
        return "harness-switch" in flat or any(w and w in flat for w in written)

    def names(word) -> bool:
        return _dynamic(word, env) or mentions(word.raw.text) or mentions(_text(word, env)) or _is_switch(
            _text(word, env), dirs, ident)

    fed_by = set()  # ids of the commands whose output may carry the switch program
    for site in shell_parse.walk(script):
        cmd = site.cmd
        if cmd.assignments:
            return False
        res = shell_parse.resolve(cmd)
        if res.unresolved or res.assignments:
            return False
        if res.head is not None and names(res.head):
            return False  # the command word: a run, not a read
        if res.name in PROOF_BANNED or any(w[0] in PROOF_BANNED for w in res.wrappers):
            return False
        if res.name == "find" and any(_text(a, env) in shell_parse._FIND_EXEC for a in res.args):
            return False
        reader = _proof_reader(res, env)
        kind = _kind(res.name or "")
        if (kind or res.payload is not None) and not reader:
            return False  # an interpreter or shell that runs code
        args = {id(w) for w in res.args}
        named = False
        for w in cmd.words:
            if names(w):
                if id(w) not in args:
                    return False  # a wrapper's word
                named = True
        for r in cmd.redirects:
            if r.hd is not None:
                body = r.hd.body
                named = named or mentions(body) or any(_is_switch(t, dirs, ident) for t in body.split()) or bool(
                    r.hd.expansions)
            elif r.target is not None and not r.writes() and r.dup is None and names(r.target):
                if res.head is None or r.fd != 0:
                    return False  # exec < F, a descriptor of a program's own: a script it may run
                named = True
        if "pipe" in site.fed:
            prev = None
            for pl, _sep in getattr(site.script, "items", ()):
                for k, stage in enumerate(pl.stages):
                    if stage is cmd and k:
                        prev = pl.stages[k - 1]
            if prev is None or not isinstance(prev, shell_parse.SimpleCommand) or id(prev) in fed_by:
                named = True
        if named:
            if not reader:
                return False
            fed_by.add(id(cmd))
    return True


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
    GIT_DIR= / GIT_COMMON_DIR= and --git-dir values; `traces`, what git writes whatever it runs:
    the files GIT_TRACE* variables name (an absolute path) and every GIT_INDEX_FILE,
    GIT_OBJECT_DIRECTORY and GIT_ALTERNATE_OBJECT_DIRECTORIES (each of its `:` parts) value, one
    whose value is not read here (UNKNOWN, or an expansion the call cannot resolve) as UNKNOWN. A GIT_WORK_TREE= and a -c core.worktree= are --work-tree directories too. `pre` holds
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
        elif GIT_WRITE_ENV.match(name):
            parts = value.split(":") if name == "GIT_ALTERNATE_OBJECT_DIRECTORIES" else [value]
            traces.extend(UNKNOWN if value == UNKNOWN or "${" in p else p for p in parts if p)
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


def _long_option(word: str, names: tuple):
    """The long option `word` (`--name` or `--name=value`) names among `names`, as git's
    parse-options reads it: the exact name, else the one name it is a unique prefix of, a
    `--no-` negation read the same way; None when it names none or several."""
    name = word[2:].partition("=")[0]
    if name in names:
        return name
    hits = [n for n in names if name and n.startswith(name)]
    if len(hits) == 1:
        return hits[0]
    if name.startswith("no-") and _long_option("--" + name[3:], names):
        return "no-" + _long_option("--" + name[3:], names)
    return None


def _config_sets_program(rest: list, ran_in: list, in_home: bool, settings: set, less_env: bool) -> bool:
    """Whether `git config <rest>` persists a program key (_program_setting, judged as a -c: alias.*,
    core.pager, core.hooksPath, include.path, a `!` value, ...) in a config the harness home's git
    reads: its repository's (in_home), --global / --system run there, or a --file / -f inside the
    home. `git config <key> <value>`, --add, --replace-all and `set` set one; --get*, --list, -l,
    --unset*, --remove-section, --blob, --edit and their `get` / `list` / ... words set none. A
    section rename (--rename-section, rename-section) can make any section a program key's: it
    counts as one. Options are read as git reads them: a long option by any unique prefix
    (`--ty`, `--fil=`, `--rename-s`), short ones clustered with -f / -t taking the rest of the word
    or the next one (`-t path`, `-zt path`), and every word after `--` positional; an unknown or
    ambiguous option fails closed where the config, or any of its words, is in the home."""
    files, pos, rename, unknown, it = [], [], False, False, iter(rest)
    for w in it:
        if w == "--":
            pos += list(it)
            break
        if w.startswith("--"):
            opt, eq, value = w[2:].partition("=")
            name = _long_option(w, GIT_CONFIG_LONG)
            if name is None:
                unknown = True
                continue
            if "--" + name in GIT_CONFIG_NO_SET:
                return False
            if name == "rename-section":
                rename = True
            elif "--" + name in GIT_CONFIG_VALUE_OPTS:
                value = value if eq else next(it, "")
                files += [value] if name == "file" else []
        elif w.startswith("-") and w != "-":
            for j, c in enumerate(w[1:], 1):
                if c in "le":
                    return False
                if c in GIT_CONFIG_SHORT_VALUE:
                    value = w[j + 1:] or next(it, "")
                    files += [value] if c == "f" else []
                    break
                if c != "z":
                    unknown = True
        else:
            pos.append(w)
    if files:
        in_home = _in_home([_resolve(f, r) for f in files for r in ran_in], settings)
    if pos[:1] and pos[0] in GIT_CONFIG_NO_SET:
        return False
    if unknown:  # git may read any word as its file: one in the home, or the home's own config, fails closed
        return in_home or _in_home([_resolve(w.partition("=")[2] if w.startswith("-") else w, r)
                                    for w in rest for r in ran_in if w.strip("-")], settings)
    if rename or pos[:1] == ["rename-section"]:
        return in_home
    pos = pos[1:] if pos[:1] == ["set"] else pos
    return in_home and len(pos) >= 2 and _program_setting("-c", pos[0] + "=" + pos[1], less_env)


def _config_attached_files(words: list, git) -> list:
    """The <file> values `git config` takes attached in a short-option cluster (`-fsettings.json`,
    `-zf<file>`), as git reads them: before `--`, past the values long options and -t take. They
    are written words, judged as the spaced `-f <file>` and `--file=<file>` forms are."""
    if git is None or git.sub is None or words[git.sub] != "config":
        return []
    out, it = [], iter(words[git.sub + 1:])
    for w in it:
        if w == "--":
            break
        if w.startswith("--"):
            name = _long_option(w, GIT_CONFIG_LONG)
            if name and "--" + name in GIT_CONFIG_VALUE_OPTS and "=" not in w:
                next(it, None)
        elif w.startswith("-") and w != "-":
            for j, c in enumerate(w[1:], 1):
                if c in GIT_CONFIG_SHORT_VALUE:
                    if w[j + 1:] and c == "f":
                        out.append(w[j + 1:])
                    elif not w[j + 1:]:
                        next(it, None)
                    break
    return out


def _init_template(rest: list, ran_in: list, settings: set, env_template: bool) -> bool:
    """Whether `git init <rest>`, run from each of `ran_in`, copies a template directory the
    command chooses (--template=<dir> by any unique prefix, or GIT_TEMPLATE_DIR, `env_template`)
    into a repository in the harness home: where git runs, or its <directory> operand. Its hooks
    and config then run there, as -c init.templateDir would."""
    template, target, it = env_template, None, iter(rest)
    for w in it:
        if w == "--":
            target = next(it, None) if target is None else target
            break
        if w.startswith("--"):
            name = _long_option(w, GIT_INIT_LONG)
            if name == "template" or name is None:
                template = True  # an unknown or ambiguous option fails closed
            if name in GIT_INIT_VALUE and "=" not in w:
                next(it, None)
        elif w in ("-b",):
            next(it, None)
        elif not w.startswith("-") and target is None:
            target = w
    if not template:
        return False
    return _in_home(ran_in + ([_resolve(target, r) for r in ran_in] if target else []), settings)


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


def _awk_at(plain: list):
    """The index in `plain` of an awk command's program word, or None when it is no reader: an
    option that loads a program or rewrites or writes files (-f / --file, -i inplace, -e, -l, -o,
    -p, ...), or no program. -v / --assign and -F / --field-separator take a value (spaced, attached
    or after `=`); `--` ends the options."""
    i, n = 1, len(plain)
    while i < n:
        w = plain[i]
        if w == "--":
            return i + 1 if i + 1 < n else None
        if w in ("-F", "-v", "--field-separator", "--assign"):
            i += 2
        elif re.fullmatch(r"-[Fv].+|--(?:field-separator|assign)=.*", w, re.S):
            i += 1
        elif w.startswith("-") and w != "-":
            return None
        else:
            return i
    return None


def _proven_literal(raw: str) -> bool:
    """Whether a word's raw shell text expands to exactly itself: single-quoted segments, double-
    quoted ones holding no $ or backtick, and unquoted characters outside AWK_UNSAFE (escaped or not)."""
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == "'":
            j = raw.find("'", i + 1)
            if j < 0:
                return False
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and raw[j] != '"':
                if raw[j] in "$`":
                    return False
                j += 2 if raw[j] == "\\" else 1
            if j >= n:
                return False
            i = j + 1
        elif c == "\\":
            if i + 1 < n and raw[i + 1] in AWK_UNSAFE:
                return False
            i += 2
        elif c in AWK_UNSAFE:
            return False
        else:
            i += 1
    return True


def _awk_parts_safe(parts, own: bool) -> bool:
    """Whether a word's parts expand without assigning and run nothing the shell does not wait for: no
    arithmetic, no process substitution anywhere (bash does not wait for one, so its code may look up
    `awk` after the last command's redirect has overwritten the awk binary), and outside awk's own
    words (`own`) no `$` expansion at all; in them a parameter only plain (AWK_PARAM_PLAIN)."""
    for p in shell_parse.active_parts(parts):
        if p.kind in ("arith", "arraylit", "procsub_in", "procsub_out"):
            return False
        if p.kind == "param" and not (own and AWK_PARAM_PLAIN.fullmatch(p.text or "")):
            return False
        if p.kind in ("cmdsub", "backtick") and not own:
            return False
    return True


def _awk_name_safe(site, final=None) -> bool:
    """Whether one simple command leaves the name `awk` resolving as before (AWK_NAME_SAFE). `final`
    is the command's last simple command when it runs alone after every other: it alone may also
    write a static file target with `>` / `>>` (`awk -F: '{print $1}' F > /tmp/keys.txt`), and then
    none of its redirects (targets, here-strings, here-documents) holds a command substitution, the
    one code bash runs after it opens that file (its words are expanded before, with no process
    substitution, background job, coproc or trap anywhere in the command)."""
    cmd = site.cmd
    if cmd is final and any(r.op in (">", ">>") and r.target is not None and r.target.value() is not None
                            and r.target.value() != "/dev/null" for r in cmd.redirects) and any(
            p.kind in ("cmdsub", "backtick") for r in cmd.redirects
            for p in shell_parse.active_parts(
                [*(r.target.parts if r.target is not None else ()), *(r.hd.expansions if r.hd is not None else ())])):
        return False
    if site.dynamic or site.templated:
        return False
    if any(not (a.name == "POSIXLY_CORRECT" and a.static_value() == "1" and cmd.words) for a in cmd.assignments):
        return False
    own = bool(cmd.words) and cmd.words[0].value() in AWKS
    for r in cmd.redirects:
        if r.fd_var is not None:  # {NAME}>x assigns NAME
            return False
        if r.op in AWK_OUT_OPS and not (r.op == ">&" and r.dup is not None) and not (
                r.op in (">", ">>") and r.target is not None and r.target.value() is not None
                and (r.target.value() == "/dev/null" or cmd is final)):
            return False
        if r.target is not None and not _awk_parts_safe(r.target.parts, own):
            return False
        if r.hd is not None and not _awk_parts_safe(r.hd.expansions, own):
            return False
    if not all(_awk_parts_safe(w.parts, own) for w in cmd.words):
        return False
    if not cmd.words:
        return True
    plain = [w.value() for w in cmd.words]
    head = plain[0]
    if head is None or "/" in head:  # a path names any program, never the awk the name resolves to
        return False
    name = os.path.basename(head)
    if ASSIGNMENT.match(head):
        return False
    if name in AWK_NAME_READERS and name not in AWK_NAME_SAFE:
        return None not in plain and _read_only(plain)
    if name not in AWK_NAME_SAFE:
        return False
    if name == "printf":
        return not (len(plain) > 1 and plain[1] is not None and plain[1].startswith("-") and plain[1] != "--")
    if name == "sed":
        return None not in plain and _sed(plain) == []  # writes nothing at all
    if name in AWKS:
        at = _awk_at([w if w is not None else "-" for w in plain])
        return at is not None and plain[at] is not None and _proven_literal(cmd.words[at].raw.text) \
            and not AWK_OUTPUT.search(plain[at])
    return True


def _awk_trusted(command) -> bool:
    """Whether every awk in `command` runs the awk program: the command names no AWK_ENV variable, the
    parser reads all of it, it and every script nested in it are _simple_list, and every simple
    command in it, nested ones too (substitutions, payloads), is _awk_name_safe. An allow rule: a
    path-named awk, hash, export, declare, typeset, readonly, local, read, mapfile, printf -v, eval,
    source, ., alias, enable, set, shopt, a sed that writes, any assignment, arithmetic, `$` outside
    awk's words, an output redirect but to /dev/null or a numbered fd, or any other command makes
    every awk in it no reader."""
    text = command.source if isinstance(command, shell_parse.Script) else command
    if AWK_ENV.search(text or ""):
        return False
    script = command if isinstance(command, shell_parse.Script) else shell_parse.parse(command)
    if script.errors() or not all(_simple_list(s) for s in (script, *shell_parse._nested_scripts(script))):
        return False
    last = script.items[-1][0] if script.items else None
    final = last.stages[0] if last is not None and len(last.stages) == 1 else None
    return all(_awk_name_safe(site, final) for site in shell_parse.walk(script))


def _simple_list(script) -> bool:
    """Whether `script` is only simple commands joined by pipes and `;` / `&&` / `||` / newlines:
    no compound command of any kind (for, select, while, until, case, if, a subshell, a group,
    coproc, `((`, `[[`, a function) and no background `&`."""
    return all(sep != "&" and all(isinstance(st, shell_parse.SimpleCommand) for st in pl.stages)
               for pl, sep in script.items)


def _raw_words(cmd) -> list | None:
    """A parsed SimpleCommand's words as raw shell text, aligned with _commands' words for it
    (assignments, words, each redirection's operator and target); None for no parsed command."""
    if cmd is None:
        return None
    raw = [w.raw.text for w in [a.word for a in cmd.assignments] + list(cmd.words)]
    for r in cmd.redirects:
        raw += [(r.io or "") + r.op, r.target.raw.text] if r.target is not None else []
    return raw


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
               members: bool = True, raw: list | None = None) -> list:
    """The words of one simple command that it writes: the paths it writes (`written`), and
    for a reader nothing else (READ_ONLY, git's readers, sed without -i, -f or e; tar -c / -t,
    its -f archive alone; with `awk`, awk whose program word is a proven literal (_proven_literal on
    its raw shell text, `raw`, aligned with `words`; the word itself where `raw` is None) with no
    > | system() or gawk `@name`; with `interpreter`,
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
        at = _awk_at(plain)
        program = plain[at] if at is not None else None
        # only a program word whose raw text expands to exactly itself is the program awk runs: a
        # brace, a glob, a $ or backtick expansion, ~ or ! may make it any other program
        k = None if at is None else len(words) - len(plain) + at
        text = None if k is None else (raw[k] if raw is not None and k < len(raw) else words[k])
        if awk and text is not None and _proven_literal(text) and not AWK_OUTPUT.search(program):
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
    sites, awk = [], _awk_trusted(command)
    segments = list(_commands(command, "code", sites=sites))
    return any(NAMES_SETTINGS.search(w) for (words, written), cmd in zip(segments, sites)
               for w in _written_by(words, written, awk=awk, interpreter=True, members=False,
                                    raw=_raw_words(cmd)))


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
    awk = _awk_trusted(script)
    for (words, written), cmd in zip(segments, sites):
        plain = _argv(words)
        if not plain:
            continue
        dirs = tuple(dict.fromkeys(_chained(chain, cmd, every_dir) + git_dirs))
        git = _git(words)
        written = list(written) + list(git.traces if git is not None else [])  # GIT_INDEX_FILE, GIT_TRACE*, ...
        written += _config_attached_files(words, git)  # `-f<file>`: git config writes that file
        head = os.path.basename(plain[0])
        interpreter = INTERPRETER.match(head) and not any(re.fullmatch(r"-[A-Za-z]*i.*", w) for w in plain[1:])
        message, moves = _message(plain), head in ("cp", "mv")
        named = [(w, head in ("rm", "rmdir", "rsync")) for w in
                 (written if (interpreter or message or moves) else _written_by(words, written, awk=awk, raw=_raw_words(cmd)))]
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
    if TYPED.search(command) and NESTED.search(command) and not _harmless_nested(script):  # unproven: as the parent
        return refuse("this Bash command types /harness into a Claude Code session, where it would reach "
                      "the switch as a prompt")
    settings, segments = _settings_files(), list(_commands(script, "all", every_word=True, sites=sites))
    every_dir, checked = _cd_dirs(segments, cwd), set()  # the call's directory and each `cd`'s, chains read through
    ident = _switch_identity()
    why = _executions(script, command, every_dir, ident) if script.error is None else None
    if why is not None:
        return refuse("this Bash command " + why + ("" if "session" not in why else
                                                    ", where it would reach the switch as a prompt"))
    proof = None  # whether the command provably only reads the switch program, worked out when needed
    chain = _chain(script, cwd)  # where each command runs, read along the chain
    shared = _shared_assignments(segments)  # an export, a lone assignment, or one before a shell
    shared += _unknown_exports(segments, shared)  # exported with a value set by printf -v, read, ...
    exported = any(GIT_CONFIG_SOURCE.match(x) for x in shared)
    carried = [x for x in shared if x.split("=", 1)[0] in GIT_TREE_ENV
               or GIT_TRACE_ENV.match(x.split("=", 1)[0]) or GIT_WRITE_ENV.match(x.split("=", 1)[0])]
    less_env = bool(LESS_ENV.search(command))
    for (words, written), cmd in zip(segments, sites):
        dirs = _chained(chain, cmd, every_dir)
        git, bases, foreign = _git(words, carried, less_env), dirs, False
        if git is not None:
            # GIT_TRACE*=<absolute path> appends git's trace there; GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY and
            # GIT_ALTERNATE_OBJECT_DIRECTORIES name what git writes; `git config -f<file>` writes <file>
            written = list(written) + git.traces + _config_attached_files(words, git)
            bases = list(dict.fromkeys(dirs + [g for d in dirs for g in _git_dirs(words, d)]))
            if UNKNOWN in git.traces:
                return refuse("this Bash command runs git with GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY, "
                              "GIT_ALTERNATE_OBJECT_DIRECTORIES or a GIT_TRACE* variable set to a value not read "
                              "here (set by read, printf -v, an expansion, ...): git writes where it names, which "
                              "can be the home's settings or the switch's state")
            if any(_in_state(_resolve(t, b)) for t in git.traces for b in bases):
                return refuse("this Bash command has git write into the switch's state (%s)" % harness_switch.DIR_NAME)
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
            if git.sub is not None and words[git.sub] == "config" and _config_sets_program(
                    words[git.sub + 1:], ran_in, in_home, settings, less_env):
                return refuse("this Bash command has git config persist a key naming a program (alias.*, "
                              "core.pager, core.hooksPath, include.path, ...) or a `!` value in config the harness "
                              "home's git reads, which can rewrite the home's settings or the switch's state")
            if git.sub is not None and words[git.sub] == "init" and _init_template(
                    words[git.sub + 1:], ran_in, settings,
                    any(x.startswith("GIT_TEMPLATE_DIR=") for x in shared + words[:git.sub])):
                return refuse("this Bash command runs git init on a repository in the harness home with a "
                              "template directory the command chooses (--template, GIT_TEMPLATE_DIR), whose hooks "
                              "and config can rewrite the home's settings or the switch's state")
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
        for word in words + _config_attached_files(words, git):  # `git config -f<file>`, as `-f <file>`; naming the
            # switch, unless the command provably only reads it
            token = word.split("=", 1)[-1]
            if os.path.basename(token.rstrip("/")) in SWITCH_PROGRAMS and not _read_only(words):
                if proof is None:
                    proof = script.error is None and _harmless_read(script, every_dir, ident)
                if not proof:
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
PROSE_META = re.compile(r"[$<>|;&\\(){}*?\[\]=`\"']")  # shell syntax: a prose file holding any on a line is no proven mention
# The one inline-code run a plain line may hold: the directory's own path alone, bounded on both sides
# by the line's start or end, a blank, or one of `.,:!`, so no letter joins its (empty) output.
PROSE_DIR_RUN = re.compile(r"(?:(?<=[\s.,:!])|^)(`+)((?:[^`\s]*/)?%s/?)\1(?=[\s.,:!]|$)"
                           % re.escape(harness_switch.DIR_NAME))
PROSE_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # bash ends a line at \n alone: \r, \f, \v ... hide one
PROSE_DIR_WORD = re.compile(r"(`*)([^\s`]*%s)/?\1[.,:!]?" % re.escape(harness_switch.DIR_NAME))
PROSE_FENCE = re.compile(r"\A {0,3}(?:```|~~~)")
PROSE_MARKER = re.compile(r"(?:[-+]|\d+[.)]|#+)")  # a Markdown list or heading marker before the first word
PROSE_PATH = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")
SHELL_WORDS = frozenset((  # bash's reserved words and builtins: a line led by one runs it under `bash x.md`
    "!", "[[", "]]", "{", "}", "case", "coproc", "do", "done", "elif", "else", "esac", "fi", "for", "function",
    "if", "in", "select", "then", "time", "until", "while", ".", ":", "[", "alias", "bg", "bind", "break",
    "builtin", "caller", "cd", "command", "compgen", "complete", "compopt", "continue", "declare", "dirs",
    "disown", "echo", "enable", "eval", "exec", "exit", "export", "false", "fc", "fg", "getopts", "hash", "help",
    "history", "jobs", "kill", "let", "local", "logout", "mapfile", "popd", "printf", "pushd", "pwd", "read",
    "readarray", "readonly", "return", "set", "shift", "shopt", "source", "suspend", "test", "times", "trap",
    "true", "type", "typeset", "ulimit", "umask", "unalias", "unset", "wait"))


def _is_command(word: str) -> bool:
    """Whether `bash x.md` would run something for a line led by `word`: a reserved word, a builtin,
    or a program on PATH or a standard bin directory (in either case, for a case-blind file system)."""
    if word in SHELL_WORDS or word.lower() in SHELL_WORDS:
        return True
    path = os.pathsep.join([os.environ.get("PATH", "")] + list(PROSE_PATH))
    return any(shutil.which(w, path=path) for w in {word, word.lower()})


def _runs_nothing(word: str) -> bool:
    """Whether bash, given `word` as a command (a line's first word or an inline-code run's text),
    provably runs nothing: the directory's own path ending in `/` with nothing glued on after it (a
    directory never runs; `dir/:` names a file in it), or a plain name, no path, that is no reserved
    word, builtin or program (trailing `.,:!` read off too)."""
    if not word:
        return True
    if "/" in word or word.startswith("~"):
        return word.endswith(harness_switch.DIR_NAME + "/") and not PROSE_META.search(word)
    return not (_is_command(word) or _is_command(word.rstrip(".,:!")))


def _plain_line(line: str) -> bool:
    """Whether bash, reading `line` anywhere in a file, provably runs nothing and opens nothing that a
    later line continues: no control character, no shell metacharacter (a backtick only in an
    inline-code run holding the directory's path alone, PROSE_DIR_RUN: any other backtick, an empty
    run or a run joined to a letter is a command substitution that can build a command), and its
    first word, also after Markdown list or heading markers and after those runs, runs nothing."""
    if PROSE_CTRL.search(line):
        return False
    ticked_ok = [True]

    def drop(m):
        ok = not PROSE_META.search(m.group(2)) and _runs_nothing(m.group(2))
        ticked_ok[0] = ticked_ok[0] and ok
        return "" if ok else m.group(0)
    if PROSE_META.search(PROSE_DIR_RUN.sub(drop, line)) or not ticked_ok[0]:
        return False
    words = [w for w in re.split(r"[ \t]+", line) if w]
    if not words:
        return True
    lead = [words[0]]
    bare = [w for w in (PROSE_DIR_RUN.sub("", w) for w in words) if w]
    lead += bare[:1]
    after = [w for w in bare if not PROSE_MARKER.fullmatch(w)]
    lead += after[:1]
    return all(_runs_nothing(PROSE_DIR_RUN.sub("", w)) for w in lead)


def _dir_mention(line: str) -> bool:
    """Whether a prose line naming the switch's state names only its directory: one word naming it,
    which no file name follows (a trailing `.` `,` `:` `!`, inline-code ticks around it allowed), no
    word starting with `-`, no other path or URL, and no indented code block."""
    if line[:1] == "\t" or line.startswith("    "):
        return False
    words = [w for w in re.split(r"[ \t]+", line) if w]
    dirs = [w for w in words if harness_switch.DIR_NAME in w]
    if len(dirs) != 1 or not PROSE_DIR_WORD.fullmatch(dirs[0]):
        return False
    return not any(w.startswith("-") or ("/" in w and w not in dirs) for w in words)


def _names_state(names: tuple, text: str, doc=None, exact=True) -> bool:
    """Whether a written file's text names the switch's state in a way that may change it: any
    mention in a file of any kind but prose (.md, .txt, .rst; by every one of `names`, the path as
    written and as resolved, so a link named x.sh is no prose); in prose, judged on the whole
    document the call leaves (`doc`, when known, else the call's text) whenever it names the state:
    refused unless EVERY line is plain (_plain_line: bash runs nothing for it and it opens no quote,
    group, substitution or continuation) and every line naming the state is a bare directory
    mention (_dir_mention) outside a fenced code block, since a rule judging lines one by one cannot
    tell what bash makes of the lines around them. `exact` False (an Edit or MultiEdit of a file
    that exists but whose resulting document cannot be read or computed byte for byte: no UTF-8, an
    old_string it does not hold) refuses prose whose call text names the state, since the client may
    apply the edit after a lossy decode or quote normalisation to a document not judged here."""
    prose = all(n.lower().endswith(PROSE) for n in names)
    if harness_switch.DIR_NAME not in text and not (prose and isinstance(doc, str)
                                                     and harness_switch.DIR_NAME in doc):
        return False
    if not prose or (not exact and harness_switch.DIR_NAME in text):
        return True
    body = doc if isinstance(doc, str) and harness_switch.DIR_NAME in doc else text
    fenced = False
    for line in body.split("\n"):
        if not _plain_line(line):
            return True
        fence = PROSE_FENCE.match(line)
        if fence:
            fenced = not fenced
        if harness_switch.DIR_NAME in line and (fenced or fence or not _dir_mention(line)):
            return True
    return False


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
    doc, exact = None, True
    prose = all(n.lower().endswith(PROSE) for n in (name, os.path.basename(raw)))
    if (harness_switch.DIR_NAME in text or prose) and tool in ("Write", "Edit", "MultiEdit"):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = _edit_result(tool, ti, fh.read())
            exact = isinstance(doc, str)  # the file exists: an edit not computed on it is unknown
        except (FileNotFoundError, NotADirectoryError):
            doc = _edit_result(tool, ti, None)  # no file: an edit with an old_string applies nowhere
        except (OSError, UnicodeDecodeError):
            doc, exact = None, tool == "Write"
    if _names_state((name, os.path.basename(raw)), text, doc, exact) and not _in_harness_checkout(path):
        return refuse("this %s writes a file naming the switch's state (%s), outside the harness" % (tool, raw))
    return 0


def check_skill(tool: str, ti: dict) -> int:
    name = str(ti.get("skill") or ti.get("command") or ti.get("name") or "").strip().lstrip("/")
    stem = name.split()[0] if name else ""
    if stem == "harness" or stem.endswith(":harness"):
        return refuse("this %s call invokes /harness" % tool)
    return 0


_PARSE_PROMPT = []  # [parse_prompt or None], loaded once


def switch_parser():
    """scripts/harness-switch's own parse_prompt (what UserPromptSubmit treats as the owner's /harness),
    compiled from its SOURCE alone (no import machinery, so no __pycache__ pyc, which an agent could plant,
    is ever read or written) and run without its main; None when it cannot be loaded."""
    if not _PARSE_PROMPT:
        fn = None
        try:
            path = SWITCH_FILES[0]
            with open(path, "rb") as f:
                source = f.read()
            code = compile(source, path, "exec", dont_inherit=True)
            namespace = {"__name__": "_harness_switch_script", "__file__": path, "__builtins__": __builtins__}
            exec(code, namespace)  # top level defines only; main runs under __name__ == "__main__"
            fn = namespace.get("parse_prompt")
            fn = fn if callable(fn) else None
        except BaseException:  # SystemExit / KeyboardInterrupt from its top level included: fail closed
            fn = None
        _PARSE_PROMPT.append(fn)
    return _PARSE_PROMPT[0]


_TAG = re.compile(r"<command-name>\s*/?\s*(?:[^<]*:)?harness\s*</command-name>")


def types_switch(text: str) -> bool:
    """Whether the switch would take `text`, arriving as a prompt, for the /harness command; fails closed
    (any `/harness` in it, or a command-name tag naming harness) when the switch's parser cannot be
    loaded or raises."""
    parse = switch_parser()
    if parse is not None:
        try:
            return parse(text) is not None
        except BaseException:
            pass
    return "/harness" in text or _TAG.search(text) is not None


def _strings(value, depth=0):
    if isinstance(value, str):
        yield value
    elif depth < 8 and isinstance(value, dict):
        for v in value.values():
            yield from _strings(v, depth + 1)
    elif depth < 8 and isinstance(value, list):
        for v in value:
            yield from _strings(v, depth + 1)


def check_prompt(tool: str, ti: dict) -> int:
    """A prompt or message (every string in the tool input, nested included) the switch would take for a typed /harness
    command; one that only mentions /harness passes."""
    for text in _strings(ti):
        if types_switch(text):
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
