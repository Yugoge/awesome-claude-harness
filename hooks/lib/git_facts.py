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
