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
