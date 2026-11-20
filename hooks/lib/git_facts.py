"""What git does with its own files and subcommands, each fact stated once for every hook.
(How a git command line parses, which word is the subcommand, lives in lib/shell_parse.py.)"""
from __future__ import annotations

import re

# A git dir's config files (config.worktree with extensions.worktreeConfig).
GIT_DIR_CONFIG_FILES = ("config", "config.worktree")
# The common-dir entries that make git run a program: the shared config and the hooks dir.
GIT_COMMON_DIR_PROTECTED = ("config", "hooks")

# Builtins whose every form only reads (output, pager and driver options aside, refused by the callers).
GIT_READ_SUBCOMMANDS = frozenset({
    "annotate", "blame", "cat-file", "check-attr", "check-ignore", "count-objects", "describe",
    "diff", "diff-files", "diff-index", "diff-tree", "for-each-ref", "grep", "log", "ls-files",
    "ls-tree", "merge-base", "name-rev", "rev-list", "rev-parse", "shortlog", "show", "show-ref",
    "status", "whatchanged",
})
# Read only in a listing form (`branch --list`, `config --get`, `stash list` ...), which a caller checks.
GIT_LISTING_SUBCOMMANDS = frozenset({"branch", "config", "reflog", "remote", "stash", "tag", "worktree"})
# Never write a working-tree file they name: add and commit read it, reflog writes only under .git.
GIT_KEEPS_NAMED_FILES = GIT_READ_SUBCOMMANDS | {"add", "commit", "reflog"}

# git config: the action options and the (2.46) subcommands that read and that write.
GIT_CONFIG_READ_OPTIONS = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "--list", "-l"})
GIT_CONFIG_WRITE_OPTIONS = frozenset({
    "--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section"})
GIT_CONFIG_READ_SUBCOMMANDS = frozenset({"get", "list"})
GIT_CONFIG_WRITE_SUBCOMMANDS = frozenset({"set", "unset", "rename-section", "remove-section", "edit"})
# The words a key-reading guard takes for a write verb: those and the action options' names, which git rejects as keys.
GIT_CONFIG_WRITE_VERBS = GIT_CONFIG_WRITE_SUBCOMMANDS | {"add", "replace-all", "unset-all"}
# Options that change only the scope a read looks in or how it prints.
GIT_CONFIG_READ_MODIFIERS = frozenset({
    "--global", "--local", "--system", "--worktree", "--show-origin", "--show-scope", "--null", "-z",
    "--name-only", "--includes", "--no-includes", "--bool", "--int", "--bool-or-int", "--path", "--expiry-date"})

# Subcommand options whose argument line names a program git runs or a file it writes.
GIT_ARGV_RUN_OR_WRITE_OPTIONS = frozenset({
    "--output", "--output-directory", "--upload-pack", "--receive-pack", "--exec", "--open-files-in-pager"})
# Those, and the options that run a program the configuration names (drivers, filters, editor, pager).
GIT_RUN_OR_WRITE_OPTIONS = GIT_ARGV_RUN_OR_WRITE_OPTIONS | {
    "--ext-diff", "--textconv", "--filters", "--edit", "--paginate"}
# The read subcommands' own exact options (git 2.54, `git <sub> -h`, `git help <sub>`) that are a prefix of one of those.
_GIT_EXACT_BEFORE_RUN = {"--text": frozenset({"diff", "diff-files", "diff-index", "diff-tree", "grep", "log", "show"}),
                         "--filter": frozenset({"cat-file"})}


def git_run_or_write_option(sub: str, word: str) -> bool:
    """Whether ``word`` given to ``git <sub>`` is an option of GIT_RUN_OR_WRITE_OPTIONS: its exact name, or an
    abbreviation of one that no exact option of ``sub`` also starts with (git: an exact option is never an
    abbreviation, and an ambiguous one is refused): `--text` is diff's own, `--textc` is `--textconv`."""
    name = word.split("=", 1)[0]
    if not name.startswith("--") or name == "--" or name in _GIT_EXACT_BEFORE_RUN and sub in _GIT_EXACT_BEFORE_RUN[name]:
        return False
    own = [o for o, subs in _GIT_EXACT_BEFORE_RUN.items() if sub in subs and o.startswith(name)]
    return name in GIT_RUN_OR_WRITE_OPTIONS or not own and any(f.startswith(name) for f in GIT_RUN_OR_WRITE_OPTIONS)

# `git remote` flags that keep it a read (a form that does not take one makes git refuse it).
GIT_REMOTE_READ_FLAGS = frozenset({"-v", "--verbose", "-n", "--push", "--all"})

# `git commit`'s long options that take a value (short: -m -F -C -c -t).
GIT_COMMIT_VALUE_OPTIONS = frozenset({
    "--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author", "--date",
    "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file"})

# Subcommands that run a shell command given on their command line (bisect run, submodule foreach,
# rebase -x, difftool -x, filter-branch's filters).
GH_MESSAGE_SUBCOMMANDS = frozenset({"issue", "pr", "release"})  # gh: words are a title or body
GIT_SHELL_PAYLOAD_SUBCOMMANDS = frozenset({"bisect", "difftool", "filter-branch", "rebase", "submodule"})

# Configuration keys whose value names a program git runs, or another config or repository it reads (`git help
# config`); a key of the families below that names neither (diff.renames, merge.conflictStyle) is a setting.
_GIT_PROGRAM_KEYS = (
    r'^(?:alias\..*|core\.(?:pager|editor|sshcommand|hookspath|fsmonitor|askpass|gitproxy|alternaterefscommand)|'
    r'pager\..*|sequence\.editor|include\..*|includeif\..*|sendemail\..*|url\..*\.(?:insteadof|pushinsteadof)|'
    r'remote\..*\.(?:uploadpack|receivepack|vcs)|submodule\..*\.update|'
    r'.*\.(?:pager|editor|command|cmd|textconv|program|helper|external|driver|path|tool|hook|sshcommand|'
    r'difffilter|clean|smudge|process))$')
GIT_PROGRAM_CONFIG_KEY_RE = re.compile(_GIT_PROGRAM_KEYS, re.IGNORECASE)
# Those, and every key of the families that hold one (matched case-insensitively, as git compares keys).
GIT_RUN_CONFIG_KEY_RE = re.compile(_GIT_PROGRAM_KEYS + r'|^(?:filter|diff|merge|gpg|uploadpack|receive|man|web|browser|'
                                   r'interactive|protocol)\..*$|^credential.*$', re.IGNORECASE)
# git's boolean spellings (an empty value reads as false).
GIT_BOOLEAN_VALUES = frozenset({"true", "false", "yes", "no", "on", "off", "1", "0", ""})


def git_config_value_names_no_program(key: str, value: str) -> bool:
    """Whether a GIT_PROGRAM_CONFIG_KEY_RE key's value names no program (`git help config`, git 2.54): a boolean for
    core.fsmonitor (false: no monitor; true: git's own built-in daemon) and pager.<cmd> (false: no pager; true: the
    pager configured elsewhere), "" or cat for core.pager (no pager), "" for diff.external (git's own diff)."""
    k = key.lower()
    if k == "core.fsmonitor" or k.startswith("pager."):
        return value.lower() in GIT_BOOLEAN_VALUES
    return (k == "core.pager" and value in ("", "cat")) or (k == "diff.external" and value == "")
