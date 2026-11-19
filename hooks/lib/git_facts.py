"""Facts about git itself that several hooks need, each stated once.

What a git command line says (which word is the subcommand, which options take a
value) is parsing and lives in lib/shell_parse.py; this module holds what git does
with its own files and subcommands. Every hook imports from here instead of
spelling the set again, so two hooks cannot give different answers about one
command.
"""
from __future__ import annotations

# The config files of a git dir: `config`, and `config.worktree` (read when
# extensions.worktreeConfig is on). Writing either changes what every later git
# run in that checkout does.
GIT_DIR_CONFIG_FILES = ("config", "config.worktree")

# The entries of a git common dir that make git run a program: the shared
# `config` (core.hooksPath, aliases, filters ...) and the default `hooks/` dir.
GIT_COMMON_DIR_PROTECTED = ("config", "hooks")

# The builtin subcommands whose every form only reads (an output, pager or external-diff option
# aside, which the callers refuse on their own). git never lets an alias shadow a builtin.
GIT_READ_SUBCOMMANDS = frozenset({
    "annotate", "blame", "cat-file", "check-attr", "check-ignore", "count-objects", "describe",
    "diff", "diff-files", "diff-index", "diff-tree", "for-each-ref", "grep", "log", "ls-files",
    "ls-tree", "merge-base", "name-rev", "rev-list", "rev-parse", "shortlog", "show", "show-ref",
    "status", "whatchanged",
})

# The subcommands that only read in their listing forms (`git branch --list`, `git config --get`,
# `git stash list`, `git reflog show` ...) and write in others; a caller checks the form.
GIT_LISTING_SUBCOMMANDS = frozenset({"branch", "config", "reflog", "remote", "stash", "tag", "worktree"})

# The subcommands that never write a working-tree file they name: the reads, add and commit (they
# read the named files into the index and a commit) and reflog (its expire and delete write only
# under .git). Not stash: `git stash push -- <file>` saves the file and reverts it.
GIT_KEEPS_NAMED_FILES = GIT_READ_SUBCOMMANDS | {"add", "commit", "reflog"}

# `git config`: the options that read (the old action options) and those that write; the subcommands
# (git 2.46) that read and those that write. get-all, get-regexp, get-urlmatch, add, replace-all and
# unset-all are not subcommands: `git config add a.b` reads `add` as a key name and fails.
GIT_CONFIG_READ_OPTIONS = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "--list", "-l",
})
GIT_CONFIG_WRITE_OPTIONS = frozenset({
    "--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section",
})
GIT_CONFIG_READ_SUBCOMMANDS = frozenset({"get", "list"})
GIT_CONFIG_WRITE_SUBCOMMANDS = frozenset({"set", "unset", "rename-section", "remove-section", "edit"})
# The options that change only which scope a read looks in or how it prints what it finds.
GIT_CONFIG_READ_MODIFIERS = frozenset({
    "--global", "--local", "--system", "--worktree", "--show-origin", "--show-scope", "--null", "-z",
    "--name-only", "--includes", "--no-includes", "--bool", "--int", "--bool-or-int", "--path",
    "--expiry-date",
})

# Subcommand options (any subcommand, a long option's unique prefix included) whose argument line
# names a program git runs or a file it writes: --output and format-patch's --output-directory write
# a file; --upload-pack, --receive-pack and --exec name the program on the other end; grep's
# --open-files-in-pager (-O) the pager it opens.
GIT_ARGV_RUN_OR_WRITE_OPTIONS = frozenset({
    "--output", "--output-directory", "--upload-pack", "--receive-pack", "--exec", "--open-files-in-pager",
})
# Those, and the options that make git run a program the configuration names: --ext-diff and
# --textconv (diff and textconv drivers), --filters (cat-file runs the clean/smudge filters), --edit
# (the editor) and --paginate (the pager).
GIT_RUN_OR_WRITE_OPTIONS = GIT_ARGV_RUN_OR_WRITE_OPTIONS | {
    "--ext-diff", "--textconv", "--filters", "--edit", "--paginate"}

# `git remote` flags that keep it a read: -v/--verbose (list with URLs), -n (`show` without asking the
# remote), --push and --all (`get-url`). Where a form does not take one, git refuses it and runs nothing.
GIT_REMOTE_READ_FLAGS = frozenset({"-v", "--verbose", "-n", "--push", "--all"})

# `git commit`'s long options that take a value (the next word, or after `=`); the short ones are
# -m -F -C -c -t (and -S, -u, whose value can only be attached).
GIT_COMMIT_VALUE_OPTIONS = frozenset({
    "--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author", "--date",
    "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file",
})

# The subcommands that run a shell command given on their own command line: `bisect run <cmd>`,
# `submodule foreach <cmd>`, `rebase --exec/-x <cmd>`, `difftool --extcmd/-x <cmd>` and filter-branch's
# --*-filter <cmd>. Not mergetool: it runs the tool the configuration names, and takes no command.
GIT_SHELL_PAYLOAD_SUBCOMMANDS = frozenset({"bisect", "difftool", "filter-branch", "rebase", "submodule"})
