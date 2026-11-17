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
             "readlink", "basename", "dirname", "find"}
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


def _commands(command: str, bodies: str, every_word: bool = False):
    """(words, written) for each simple command `command` runs (_redirected's, without the count)."""
    for words, written, _ in _redirected(command, bodies, every_word):
        yield words, written


def _redirected(command: str, bodies: str, every_word: bool = False, depth: int = 0):
    """(words, written, n) for each simple command `command` runs, as hooks/lib/shell_parse.py reads it:
    its words as text (assignments, words, then each redirection's operator and target) and the
    paths shell_parse.write_targets says it writes. A -c or eval payload, a substitution and a
    heredoc a shell reads are commands; so is any other heredoc's body where `bodies` keeps it
    ("all"; "code": unless it feeds a commit, tag or PR message; "shell": none). With `every_word`
    a word holding a space or ; | & is read as commands too. A $NAME is read from the call's
    environment or an assignment before it; text the parser cannot read is split on whitespace,
    a word after a redirection operator, or attached to one, written. `n` counts the words before
    the redirections (all of them where the parser cannot read the text)."""
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
        n = len(words)
        for r in cmd.redirects:
            words += [(r.io or "") + r.op, _text(r.target, env)] if r.target is not None else []
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if plain and _message(plain):
            message.append(level)
        yield words, written, n
        for w in words if every_word and depth < 3 else ():
            if any(c in w for c in " ;|&\n"):
                yield from _redirected(w, bodies, every_word, depth + 1)
        shell = shell_parse.resolve(cmd).payload_kind == "heredoc_shell"
        for r in cmd.redirects if bodies == "all" or (bodies == "code" and not message) else ():
            if r.hd is not None and not shell and depth < 3:
                yield from _redirected(r.hd.body, bodies, every_word, depth + 1)
    for word in [w for ws in targets.values() for w in ws]:  # a redirection of a compound command
        yield [">", _text(word, env)], [_text(word, env)], 0
    for line in command.splitlines() if script.error is not None else ():
        words = line.split()
        yield words, [m.group(1) or nxt for w, nxt in zip(words, words[1:] + [""]) for m in [FALLBACK_REDIRECT.match(w)] if m], len(words)


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
    return head in READ_ONLY and "-delete" not in words and "-exec" not in words


def _written_words(words: list, written: list, everything=None) -> list:
    """The words of one simple command that name what it writes: the paths it writes, and, for a
    command that is not read-only (cp, mv, tee, sed -i, python, ...), every word (`everything`
    False: the paths alone)."""
    plain = [w for w in words if not ASSIGNMENT.match(w)]
    if everything is None:
        everything = bool(plain) and not _read_only(plain)
    if everything and os.path.basename(plain[0]) == "sed":
        everything = any(re.fullmatch(r"-[A-Za-z]*i.*|--in-place.*", w) for w in plain[1:])
    return written + (words if everything else [])


def writes_settings_file(command: str) -> bool:
    """True when `command` writes a settings*.json file, in any directory."""
    return any(NAMES_SETTINGS.search(w) for words, written in _commands(command, "code")
               for w in _written_words(words, written))


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
    destination, and mv's sources. A path is read from the call's directory and every `cd`'s.
    Each directory, and each word with its kind, is read once: a command padded with repeated
    `cd .` costs what its distinct words cost, not their count times its segments'."""
    segments = list(_commands(command, "shell"))
    cds = dict.fromkeys(w[1] for w, _ in segments if len(w) > 1 and os.path.basename(w[0]) in ("cd", "pushd"))
    dirs = list(dict.fromkeys([cwd] + [_resolve(w, cwd) for w in cds]
                              + [d for w, _ in segments for d in _git_dirs(w, cwd)]))
    out, seen, home = [], set(), _settings_files()
    for words, written in segments:
        plain = [w for w in words if not ASSIGNMENT.match(w)]
        if not plain:
            continue
        git = _git(words)
        written = written + list((git or GitCall(None, (), False, False, False, [], [])).traces)
        written += _config_attached_files(words, git)  # `-f<file>`: git config writes that file
        head = os.path.basename(plain[0])
        interpreter = INTERPRETER.match(head) and not any(re.fullmatch(r"-[A-Za-z]*i.*", w) for w in plain[1:])
        message, moves = _message(plain), head in ("cp", "mv")
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
    if TYPED.search(command) and NESTED.search(command):
        return refuse("this Bash command types /harness into a Claude Code session, where it would reach "
                      "the switch as a prompt")
    settings, segments = _settings_files(), list(_redirected(command, "all", every_word=True))
    pairs = [(w, written) for w, written, _ in segments]
    cds = [_resolve(".", cwd)] + [_resolve(w[1], cwd) for w, _ in pairs if len(w) > 1 and os.path.basename(w[0]) in ("cd", "pushd")]
    shared = _shared_assignments(pairs)  # an export, a lone assignment, or one before a shell
    shared += _unknown_exports(pairs, shared)  # exported with a value set by printf -v, read, ...
    exported = any(GIT_CONFIG_SOURCE.match(x) for x in shared)
    carried = [x for x in shared if x.split("=", 1)[0] in GIT_TREE_ENV
               or GIT_TRACE_ENV.match(x.split("=", 1)[0]) or GIT_WRITE_ENV.match(x.split("=", 1)[0])]
    less_env, every_base = bool(LESS_ENV.search(command)), list(dict.fromkeys([cwd] + cds))
    for words, written, n in segments:
        git, bases = _git(words, carried, less_env), every_base  # the call's directory and each `cd`'s
        # after git, a redirection writes its own target (`written`), never a reading git's path words
        writes = bool(WRITES.search(" ".join(words[:n] if git is not None else words))) or not _read_only(words)
        if git is not None:
            written = written + git.traces  # GIT_TRACE*=<absolute path> appends git's trace there; GIT_INDEX_FILE ...
            if UNKNOWN in git.traces:
                return refuse("this Bash command runs git with GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY, "
                              "GIT_ALTERNATE_OBJECT_DIRECTORIES or a GIT_TRACE* variable set to a value not read "
                              "here (set by read, printf -v, an expansion, ...): git writes where it names, which "
                              "can be the home's settings or the switch's state")
            if any(_in_state(_resolve(t, b)) for t in git.traces for b in bases + _git_dirs(words, cwd)):
                return refuse("this Bash command has git write into the switch's state (%s)" % harness_switch.DIR_NAME)
            bases = bases + _git_dirs(words, cwd)
            ran_in = [(_git_dirs(words, d) or [d])[-1] for d in dict.fromkeys(cds)]  # from each `cd`
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
            if _foreign_config(git, ran_in, settings, exported) or _foreign_tree(git, cds, settings):
                if in_home:
                    return refuse("this Bash command runs git in the harness home with config the command chooses "
                                  "(HOME, XDG_CONFIG_HOME, GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM, GIT_DIR, "
                                  "GIT_COMMON_DIR or a --git-dir of another repository, or the home as the work tree "
                                  "of another repository), whose diff.external, alias, hook "
                                  "or pager can rewrite the home's settings or the switch's state")
                if git.sub is not None and _in_home([_resolve(w.split("=", 1)[-1] if w.startswith("-") else w, r)
                                                     for w in words[git.sub + 1:] for r in ran_in], settings):
                    writes = True  # git reads a harness-home path under config the command chooses
        attached = _config_attached_files(words, git)  # `git config -f<file>`, judged as `-f <file>`
        for word, writes_word in [(w, writes) for w in words + attached] + [(w, True) for w in written]:  # every redirect
            token = word.split("=", 1)[-1]  # target is written, whatever its fd (1>, 2>>, &>, >|)
            if os.path.basename(token.rstrip("/")) in SWITCH_PROGRAMS and not _read_only(words):
                return refuse("this Bash command runs the switch (%s)" % os.path.basename(token))
            if harness_switch.DIR_NAME in token and writes_word:
                return refuse("this Bash command changes the switch's state (%s)" % harness_switch.DIR_NAME)
            if os.path.basename(token) in SETTINGS_NAMES and writes_word and not _allow_settings(cwd):
                if any(_resolve(token, base) in settings for base in bases):
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
