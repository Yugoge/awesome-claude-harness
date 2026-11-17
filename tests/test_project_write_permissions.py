"""OB-L08: project writes are allowed by `Edit(./**)`; the harness home and home dot-state ask again.

Root cause: permissions.allow's Edit entries covered only manifests, .claude/agents|commands, .review,
docs, scripts and tests/generated, so every other write inside the project (Write `src/newmodule.py`,
`echo hi > notes.md`, a heredoc written to a project file) asked in default mode, and was refused
outright headless or overnight. The owner chose `Edit(./**)` (not defaultMode acceptEdits).

`./**` anchors at the session's current directory, so with the current directory at a harness clone
installed through CLAUDE_CONFIG_DIR (docs/installation.md, "Other install locations") or at the home
directory it also allowed writes that asked before: anything in the harness home (hooks, policies,
settings, templates, the venv whose interpreter the registered hooks run, the hash-locked requirements,
private-literals.txt, ...) and the account's dot-state (~/.ssh, ~/.netrc, ~/.config/..., ~/.local/bin).
permissions.ask returns the Write/Edit route to those to a prompt:

* anchored at the settings source (a single leading slash: the harness home in both install layouts,
  code.claude.com/docs/en/permissions.md "`/path` | Path relative to the settings source"): one entry
  per top-level entry of the harness home -- each tracked file and directory, each runtime entry its
  .gitignore names, and each name Claude Code itself reads from its config directory (CLI_READ: rules/,
  output-styles/, CLAUDE.local.md, keybindings.json, .mcp.json, ...; in a CLAUDE_CONFIG_DIR install the
  config directory is the harness home, and `<config>/rules/*.md` is loaded into every session like
  CLAUDE.md) -- held to that universe by test_every_harness_home_entry_is_asked;
* anchored at the home directory, for its dot files and dot directories: `~/.?` ... `~/.?????` and
  `~/.???????*` (every dot name of 1-5 or 7+ characters, with everything below it) and the six-character
  names `~/.config`, `~/.curlrc`, `~/.docker`, `~/.dotnet`, `~/.gradle`, `~/.mailrc`, `~/.ollama`,
  `~/.pgpass`, `~/.psqlrc`, `~/.pypirc`, `~/.rustup`, `~/.sdkman`, `~/.vscode`, `~/.wgetrc`. Not `~/.*`:
  measured, a pattern naming a directory covers what is below it, so `~/.*` (and `~/.*/**`) also covered
  `~/.claude/projects/<p>/memory/*.md`, the CLI's auto-memory, which base allowed; `.claude` is six
  characters, so the length patterns leave it out. The six-character list also names `~/.cursor`,
  `~/.gemini` (other agents' MCP configuration), `~/.rhosts`, `~/.shosts`, `~/.my.cnf`, `~/.tcshrc`,
  `~/.bundle` and `~/.nanorc`; any other six-character dot name is written unprompted from HOME.

"Rules are evaluated in order: deny, then ask, then allow" (permissions.md); every deny of the base
settings is measured still denying below.

Harness-home paths that stay writable without a prompt, by design:

* RESIDUAL: `docs/**`, `scripts/**`, `requirements.txt`, `tests/generated/**` -- base allowed them
  through its cwd-relative allow entries (`Edit(docs/**)`, `Edit(scripts/**)`, `Edit(**/requirements.txt)`,
  `Edit(tests/generated/**)`) with the current directory at the clone, and an ask would newly prompt
  that. `scripts/**` is executed by settings and hooks; that exposure predates OB-L08.
* CLI_OWNED: `projects/**` except transcripts (`Edit(/projects/**/*.jsonl)` asks), `plans/**`,
  `workflows/**`, `jobs/**`, `agent-memory/**` -- directories where the CLI grants its own session's files
  (auto-memory, plan files, workflow scripts, background-job scratch, subagent memory) ahead of the rules.
  An ask over `projects/**` (or `~/.*`) was measured prompting the current session's auto-memory writes,
  which base allowed; an ask cannot spare the current session's file and catch another's, so another
  project's memory, a plan file, a workflow script and job scratch in a CLAUDE_CONFIG_DIR clone are written
  unprompted (measured; base asked them).
* a new top-level name that neither the harness nor the CLI reads.
* the Bash output-redirect gap the owner accepted: ask rules do not reach a redirect target
  (permissions.md, Redirections: the check "covers your `Edit` allow and deny rules, protected paths, and
  the working directories"), measured so.

MEASURED and MEASURED_HOME hold the decisions of Claude Code 2.1.326's own permission check, run headless
offline (`claude -p --permission-mode default` against a local mock of the Messages API that answers
with the one tool call; a throwaway HOME laid out as a harness home, the settings file holding only the
`permissions` block under test; no hook registered). Columns: label, current directory (proj = a git
project under HOME, home = HOME, harness = ~/.claude, alt = a clone used as CLAUDE_CONFIG_DIR, althome =
HOME with that clone as CLAUDE_CONFIG_DIR, repo = a plain clone under HOME), tool, argument, then the
decision with the base settings (origin/claude/train-c @ d1abc798), with the first OB-L08 commit
(c1f2e447, `Edit(./**)` only) and with this settings.json. allow = the write happened, ask = "Claude
requested permissions ..." / "Output redirection ...", deny = "denied by your permission settings",
n/a = the Write tool refused an existing file not read first (no permission decision seen).

Bracket expressions are no way to narrow `./**`: `Edit(./[!.]*)`, `Edit(./[^.]*)` and
`Edit(./[a-zA-Z0-9_]*)` were measured matching dot entries and not `src/...`; a Bash ask rule cannot
see a redirect (`Bash(*>*hooks/*)` and similar left the redirects allowed). `Edit(/tests/*)` was
measured matching `tests/generated/x.py` (a directory pattern covers what is below it), hence the
per-subdirectory entries under tests/.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"

RESIDUAL = {"docs", "scripts", "requirements.txt", "tests/generated"}
CLI_OWNED = {"projects", "plans", "workflows", "jobs", "agent-memory"}
# Entries a deny entry or the CLI's own protection already stops (permissions.deny, protected paths).
OTHERWISE_STOPPED = {".harness-switch", ".env", "*.key", "*.pem", ".claude.json", "settings.local.json",
                     "/settings.machine.json"}
# .gitignore lines naming a kind of file at any depth (editor, OS and log debris), not a harness-home entry.
GENERIC = {"*.tmp", "*.log", "*.backup", "*.bak", ".DS_Store", "Thumbs.db"}
SIX = ["bundle", "config", "cursor", "curlrc", "docker", "dotnet", "gemini", "gradle", "mailrc", "my.cnf", "nanorc",
       "ollama", "pgpass", "psqlrc", "pypirc", "rhosts", "rustup", "sdkman", "shosts", "tcshrc", "vscode", "wgetrc"]
# What Claude Code reads from its config directory (code.claude.com docs: memory, settings, sub-agents, slash
# commands, skills, hooks, output styles, statusline, keybindings, MCP, plugins; and what the probes saw load).
CLI_READ = ["agents", "commands", "skills", "hooks", "output-styles", "rules", "CLAUDE.md", "CLAUDE.local.md",
            "settings.json", "settings.local.json", "keybindings.json", "statusline.sh", "plugins", ".mcp.json",
            ".claude.json", "themes", "mods", "dev-mods", "ide", "teams", "memory", "hooks.json", "remote-settings.json",
            "projects", "plans", "workflows", "jobs", "agent-memory"]
HOME_ASKS = ["Edit(~/.?)", "Edit(~/.??)", "Edit(~/.???)", "Edit(~/.????)", "Edit(~/.?????)", "Edit(~/.???????*)"] + \
    ["Edit(~/.%s)" % n for n in SIX]
MEASURED_ASK = [
    'Edit(/.claude/**)',
    'Edit(/.gitattributes)',
    'Edit(/.github/**)',
    'Edit(/.gitignore)',
    'Edit(/AGENTS.md)',
    'Edit(/ARCHITECTURE.md)',
    'Edit(/CHANGELOG.md)',
    'Edit(/CLAUDE.md)',
    'Edit(/INDEX.md)',
    'Edit(/LICENSE)',
    'Edit(/NOTICE)',
    'Edit(/PUBLIC-CORE.md)',
    'Edit(/README.md)',
    'Edit(/VERSION)',
    'Edit(/agents/**)',
    'Edit(/commands/**)',
    'Edit(/conftest.py)',
    'Edit(/examples/**)',
    'Edit(/hooks/**)',
    'Edit(/policies/**)',
    'Edit(/push.sh)',
    'Edit(/pytest.ini)',
    'Edit(/release-membership.v1.json)',
    'Edit(/requirements/**)',
    'Edit(/schemas/**)',
    'Edit(/settings*.json)',
    'Edit(/skills/**)',
    'Edit(/templates/**)',
    'Edit(/tools/**)',
    'Edit(/tests/*.*)',
    'Edit(/tests/artifact_graph/**)',
    'Edit(/tests/differential/**)',
    'Edit(/tests/fixtures/**)',
    'Edit(/tests/instructions/**)',
    'Edit(/tests/lint/**)',
    'Edit(/tests/replay/**)',
    'Edit(/tests/scripts/**)',
    'Edit(/tests/shell_parse/**)',
    'Edit(/tests/__pycache__/**)',
    'Edit(/tests/reports/**)',
    'Edit(/venv/**)',
    'Edit(/.venv/**)',
    'Edit(/env/**)',
    'Edit(/node_modules/**)',
    'Edit(/__pycache__/**)',
    'Edit(/todos/**)',
    'Edit(/shell-snapshots/**)',
    'Edit(/debug/**)',
    'Edit(/plugins/**)',
    'Edit(/statsig/**)',
    'Edit(/logs/**)',
    'Edit(/session-env/**)',
    'Edit(/file-history/**)',
    'Edit(/sessions/**)',
    'Edit(/attribution-seals/**)',
    'Edit(/dev-registry/**)',
    'Edit(/dev-start-replays/**)',
    'Edit(/paseo-daemon/**)',
    'Edit(/scratch/**)',
    'Edit(/session-resources/**)',
    'Edit(/specs/**)',
    'Edit(/state/**)',
    'Edit(/archive/**)',
    'Edit(/backups/**)',
    'Edit(/cache/**)',
    'Edit(/paste-cache/**)',
    'Edit(/restart-state/**)',
    'Edit(/tasks/**)',
    'Edit(/graphify-out/**)',
    'Edit(/.playwright-mcp/**)',
    'Edit(/worktrees/**)',
    'Edit(/.credentials.json)',
    'Edit(/private-literals.txt)',
    'Edit(/history.jsonl)',
    'Edit(/.doc-sync-cache.json)',
    'Edit(/mcp-needs-auth-cache.json)',
    'Edit(/.last-cleanup)',
    'Edit(/playwright-storage-state.json)',
    'Edit(/agent-scores.json)',
    'Edit(/agent-scores.json.lock)',
    'Edit(/.hook-refactor-allow)',
    'Edit(/overnight-*)',
    'Edit(/workflow-*)',
    'Edit(/.settings.render.*)',
    'Edit(/*.bak-*)',
    'Edit(/settings.json.backup.*)',
    'Edit(/*.png)',
    'Edit(/projects/**/*.jsonl)',
    'Edit(/rules/**)',
    'Edit(/output-styles/**)',
    'Edit(/themes/**)',
    'Edit(/mods/**)',
    'Edit(/dev-mods/**)',
    'Edit(/ide/**)',
    'Edit(/teams/**)',
    'Edit(/memory/**)',
    'Edit(/CLAUDE.local.md)',
    'Edit(/keybindings.json)',
    'Edit(/statusline*)',
    'Edit(/.mcp.json)',
    'Edit(/.claude.json)',
    'Edit(/hooks.json)',
    'Edit(/remote-settings.json)',
    'Edit(~/.?)',
    'Edit(~/.??)',
    'Edit(~/.???)',
    'Edit(~/.????)',
    'Edit(~/.?????)',
    'Edit(~/.???????*)',
    'Edit(~/.bundle)',
    'Edit(~/.config)',
    'Edit(~/.cursor)',
    'Edit(~/.curlrc)',
    'Edit(~/.docker)',
    'Edit(~/.dotnet)',
    'Edit(~/.gemini)',
    'Edit(~/.gradle)',
    'Edit(~/.mailrc)',
    'Edit(~/.my.cnf)',
    'Edit(~/.nanorc)',
    'Edit(~/.ollama)',
    'Edit(~/.pgpass)',
    'Edit(~/.psqlrc)',
    'Edit(~/.pypirc)',
    'Edit(~/.rhosts)',
    'Edit(~/.rustup)',
    'Edit(~/.sdkman)',
    'Edit(~/.shosts)',
    'Edit(~/.tcshrc)',
    'Edit(~/.vscode)',
    'Edit(~/.wgetrc)',
]

MEASURED = [
    ('P1 Write src/newmodule.py', 'proj', 'Write', 'src/newmodule.py', 'ask', 'allow', 'allow'),
    ('P2 echo hi > notes.md', 'proj', 'Bash', 'echo X > notes.md', 'ask', 'allow', 'allow'),
    ('P3 heredoc > project file', 'proj', 'Bash', "cat > src/gen.py <<'EOF'\nX\nEOF", 'ask', 'allow', 'allow'),
    ('P4 Write top-level README2.md', 'proj', 'Write', 'README2.md', 'ask', 'allow', 'allow'),
    ('R Write .claude/settings.json', 'proj', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('R echo > .claude/settings.json', 'proj', 'Bash', 'echo X > .claude/settings.json', 'deny', 'deny', 'deny'),
    ('R Write .claude/settings.local.json', 'proj', 'Write', '.claude/settings.local.json', 'ask', 'deny', 'deny'),
    ('R echo > .claude/settings.local.json', 'proj', 'Bash', 'echo X > .claude/settings.local.json', 'ask', 'deny', 'deny'),
    ('R Write .claude/hooks/x.sh', 'proj', 'Write', '.claude/hooks/x.sh', 'deny', 'deny', 'deny'),
    ('R echo > .claude/hooks/x.sh', 'proj', 'Bash', 'echo X > .claude/hooks/x.sh', 'deny', 'deny', 'deny'),
    ('R Write .claude/commands/x.md', 'proj', 'Write', '.claude/commands/x.md', 'ask', 'ask', 'ask'),
    ('R echo > .claude/commands/x.md', 'proj', 'Bash', 'echo X > .claude/commands/x.md', 'ask', 'ask', 'ask'),
    ('R Write .env', 'proj', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('R echo > .env', 'proj', 'Bash', 'echo X > .env', 'deny', 'deny', 'deny'),
    ('R Write .env.local', 'proj', 'Write', '.env.local', 'deny', 'deny', 'deny'),
    ('R echo > .env.local', 'proj', 'Bash', 'echo X > .env.local', 'deny', 'deny', 'deny'),
    ('R Write .git/config', 'proj', 'Write', '.git/config', 'n/a', 'n/a', 'n/a'),
    ('R echo > .git/config', 'proj', 'Bash', 'echo X > .git/config', 'ask', 'ask', 'ask'),
    ('R Write .git/hooks/pre-commit', 'proj', 'Write', '.git/hooks/pre-commit', 'ask', 'ask', 'ask'),
    ('R echo > .git/hooks/pre-commit', 'proj', 'Bash', 'echo X > .git/hooks/pre-commit', 'ask', 'ask', 'ask'),
    ('R Write .claude/CLAUDE.md', 'proj', 'Write', '.claude/CLAUDE.md', 'deny', 'deny', 'deny'),
    ('R echo > .claude/CLAUDE.md', 'proj', 'Bash', 'echo X > .claude/CLAUDE.md', 'deny', 'deny', 'deny'),
    ('R Write .claude/scripts/x.sh', 'proj', 'Write', '.claude/scripts/x.sh', 'deny', 'deny', 'deny'),
    ('R echo > .claude/scripts/x.sh', 'proj', 'Bash', 'echo X > .claude/scripts/x.sh', 'deny', 'deny', 'deny'),
    ('R Write .claude/agents/x.md', 'proj', 'Write', '.claude/agents/x.md', 'ask', 'ask', 'ask'),
    ('R echo > .claude/agents/x.md', 'proj', 'Bash', 'echo X > .claude/agents/x.md', 'ask', 'ask', 'ask'),
    ('R Write src/.env', 'proj', 'Write', 'src/.env', 'deny', 'deny', 'deny'),
    ('R echo > src/.env', 'proj', 'Bash', 'echo X > src/.env', 'deny', 'deny', 'deny'),
    ('R Write config/secret.yaml', 'proj', 'Write', 'config/secret.yaml', 'deny', 'deny', 'deny'),
    ('R echo > config/secret.yaml', 'proj', 'Bash', 'echo X > config/secret.yaml', 'deny', 'deny', 'deny'),
    ('R Write .mcp.json', 'proj', 'Write', '.mcp.json', 'ask', 'ask', 'ask'),
    ('R echo > .mcp.json', 'proj', 'Bash', 'echo X > .mcp.json', 'ask', 'ask', 'ask'),
    ('R Write .gitmodules', 'proj', 'Write', '.gitmodules', 'ask', 'ask', 'ask'),
    ('R echo > .gitmodules', 'proj', 'Bash', 'echo X > .gitmodules', 'ask', 'ask', 'ask'),
    ('R Write .claude/skills/x/SKILL.md', 'proj', 'Write', '.claude/skills/x/SKILL.md', 'ask', 'ask', 'ask'),
    ('R echo > .claude/skills/x/SKILL.md', 'proj', 'Bash', 'echo X > .claude/skills/x/SKILL.md', 'ask', 'ask', 'ask'),
    ('R Write .vscode/settings.json', 'proj', 'Write', '.vscode/settings.json', 'ask', 'ask', 'ask'),
    ('R echo > .vscode/settings.json', 'proj', 'Bash', 'echo X > .vscode/settings.json', 'ask', 'ask', 'ask'),
    ('R Write .claude/x.md', 'proj', 'Write', '.claude/x.md', 'ask', 'ask', 'ask'),
    ('R echo > .claude/x.md', 'proj', 'Bash', 'echo X > .claude/x.md', 'ask', 'ask', 'ask'),
    ('R Write .harness-switch/x', 'proj', 'Write', '.harness-switch/x', 'deny', 'deny', 'deny'),
    ('R echo > .harness-switch/x', 'proj', 'Bash', 'echo X > .harness-switch/x', 'deny', 'deny', 'deny'),
    ('R tee .claude/settings.json', 'proj', 'Bash', 'echo X | tee .claude/settings.json', 'deny', 'deny', 'deny'),
    ('R heredoc .claude/settings.local.json', 'proj', 'Bash', "cat > .claude/settings.local.json <<'EOF'\nX\nEOF", 'ask', 'deny', 'deny'),
    ('R echo >> .git/config', 'proj', 'Bash', 'echo X >> .git/config', 'ask', 'ask', 'ask'),
    ('R ./.claude/settings.local.json', 'proj', 'Write', './.claude/../.claude/settings.local.json', 'ask', 'deny', 'deny'),
    ('R .CLAUDE/settings.local.json case', 'proj', 'Write', '.Claude/settings.local.json', 'ask', 'deny', 'deny'),
    ('H Write hooks/x.py', 'harness', 'Write', 'hooks/x.py', 'ask', 'ask', 'ask'),
    ('H echo >> hooks/x.py', 'harness', 'Bash', 'echo X >> hooks/x.py', 'ask', 'ask', 'ask'),
    ('H Write hooks/pretool-launch.py', 'harness', 'Write', 'hooks/pretool-launch.py', 'n/a', 'n/a', 'n/a'),
    ('H echo >> hooks/pretool-launch.py', 'harness', 'Bash', 'echo X >> hooks/pretool-launch.py', 'ask', 'ask', 'ask'),
    ('H Write scripts/x.sh', 'harness', 'Write', 'scripts/x.sh', 'ask', 'ask', 'ask'),
    ('H echo >> scripts/x.sh', 'harness', 'Bash', 'echo X >> scripts/x.sh', 'ask', 'ask', 'ask'),
    ('H Write settings.json', 'harness', 'Write', 'settings.json', 'n/a', 'n/a', 'n/a'),
    ('H echo >> settings.json', 'harness', 'Bash', 'echo X >> settings.json', 'ask', 'ask', 'ask'),
    ('H Write CLAUDE.md', 'harness', 'Write', 'CLAUDE.md', 'n/a', 'n/a', 'n/a'),
    ('H echo >> CLAUDE.md', 'harness', 'Bash', 'echo X >> CLAUDE.md', 'ask', 'ask', 'ask'),
    ('H Write settings.local.json', 'harness', 'Write', 'settings.local.json', 'ask', 'ask', 'ask'),
    ('H echo >> settings.local.json', 'harness', 'Bash', 'echo X >> settings.local.json', 'ask', 'ask', 'ask'),
    ('H Write lib/x.py', 'harness', 'Write', 'lib/x.py', 'ask', 'ask', 'ask'),
    ('H echo >> lib/x.py', 'harness', 'Bash', 'echo X >> lib/x.py', 'ask', 'ask', 'ask'),
    ('H Write commands/x.md', 'harness', 'Write', 'commands/x.md', 'ask', 'ask', 'ask'),
    ('H echo >> commands/x.md', 'harness', 'Bash', 'echo X >> commands/x.md', 'ask', 'ask', 'ask'),
    ('H Write new.md', 'harness', 'Write', 'new.md', 'ask', 'ask', 'ask'),
    ('H echo >> new.md', 'harness', 'Bash', 'echo X >> new.md', 'ask', 'ask', 'ask'),
    ('H heredoc hooks/x.py', 'harness', 'Bash', "cat > hooks/x.py <<'EOF'\nX\nEOF", 'ask', 'ask', 'ask'),
    ('C Write hooks/x.py', 'repo', 'Write', 'hooks/x.py', 'ask', 'allow', 'allow'),
    ('C echo >> hooks/x.py', 'repo', 'Bash', 'echo X >> hooks/x.py', 'ask', 'allow', 'allow'),
    ('C Write scripts/x.sh', 'repo', 'Write', 'scripts/x.sh', 'allow', 'allow', 'allow'),
    ('C echo >> scripts/x.sh', 'repo', 'Bash', 'echo X >> scripts/x.sh', 'allow', 'allow', 'allow'),
    ('C Write settings.json', 'repo', 'Write', 'settings.json', 'n/a', 'n/a', 'n/a'),
    ('C echo >> settings.json', 'repo', 'Bash', 'echo X >> settings.json', 'ask', 'allow', 'allow'),
    ('C Write CLAUDE.md', 'repo', 'Write', 'CLAUDE.md', 'n/a', 'n/a', 'n/a'),
    ('C echo >> CLAUDE.md', 'repo', 'Bash', 'echo X >> CLAUDE.md', 'ask', 'allow', 'allow'),
    ('X Write ~/.claude/hooks/x.py from proj', 'proj', 'Bash', 'echo X > ~/.claude/hooks/x.py', 'ask', 'ask', 'ask'),
    ('X echo > ../.claude/hooks/x.py from proj', 'proj', 'Bash', 'echo X > ../.claude/hooks/x.py', 'ask', 'ask', 'ask'),
    ('M Write .bashrc', 'home', 'Write', '.bashrc', 'n/a', 'n/a', 'n/a'),
    ('M echo >> .bashrc', 'home', 'Bash', 'echo X >> .bashrc', 'ask', 'ask', 'ask'),
    ('M Write .ssh/authorized_keys', 'home', 'Write', '.ssh/authorized_keys', 'ask', 'allow', 'ask'),
    ('M echo >> .ssh/authorized_keys', 'home', 'Bash', 'echo X >> .ssh/authorized_keys', 'ask', 'allow', 'allow'),
    ('M Write .gitconfig', 'home', 'Write', '.gitconfig', 'n/a', 'n/a', 'n/a'),
    ('M echo >> .gitconfig', 'home', 'Bash', 'echo X >> .gitconfig', 'ask', 'ask', 'ask'),
    ('M Write .aws/credentials', 'home', 'Write', '.aws/credentials', 'deny', 'deny', 'deny'),
    ('M echo >> .aws/credentials', 'home', 'Bash', 'echo X >> .aws/credentials', 'deny', 'deny', 'deny'),
    ('M Write .profile', 'home', 'Write', '.profile', 'ask', 'ask', 'ask'),
    ('M echo >> .profile', 'home', 'Bash', 'echo X >> .profile', 'ask', 'ask', 'ask'),
    ('M Write .claude/settings.json', 'home', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('M echo >> .claude/settings.json', 'home', 'Bash', 'echo X >> .claude/settings.json', 'deny', 'deny', 'deny'),
    ('M Write .claude/hooks/x.py', 'home', 'Write', '.claude/hooks/x.py', 'deny', 'deny', 'deny'),
    ('M echo >> .claude/hooks/x.py', 'home', 'Bash', 'echo X >> .claude/hooks/x.py', 'deny', 'deny', 'deny'),
    ('M Write .claude/CLAUDE.md', 'home', 'Write', '.claude/CLAUDE.md', 'deny', 'deny', 'deny'),
    ('M echo >> .claude/CLAUDE.md', 'home', 'Bash', 'echo X >> .claude/CLAUDE.md', 'deny', 'deny', 'deny'),
    ('M Write .claude/scripts/x.sh', 'home', 'Write', '.claude/scripts/x.sh', 'deny', 'deny', 'deny'),
    ('M echo >> .claude/scripts/x.sh', 'home', 'Bash', 'echo X >> .claude/scripts/x.sh', 'deny', 'deny', 'deny'),
    ('M Write .claude.json', 'home', 'Write', '.claude.json', 'n/a', 'n/a', 'n/a'),
    ('M echo >> .claude.json', 'home', 'Bash', 'echo X >> .claude.json', 'ask', 'ask', 'ask'),
    ('A Write hooks/x.py', 'alt', 'Write', 'hooks/x.py', 'ask', 'allow', 'ask'),
    ('A Write scripts/x.sh', 'alt', 'Write', 'scripts/x.sh', 'allow', 'allow', 'allow'),
    ('A Write policies/x.json', 'alt', 'Write', 'policies/x.json', 'ask', 'allow', 'ask'),
    ('A Write new.md', 'alt', 'Write', 'new.md', 'ask', 'allow', 'allow'),
    ('A echo >> hooks/x.py', 'alt', 'Bash', 'echo X >> hooks/x.py', 'ask', 'allow', 'allow'),
    ('A echo >> settings.json', 'alt', 'Bash', 'echo X >> settings.json', 'ask', 'ask', 'ask'),
    ('A echo >> CLAUDE.md', 'alt', 'Bash', 'echo X >> CLAUDE.md', 'ask', 'allow', 'allow'),
    ('A echo >> settings.local.json', 'alt', 'Bash', 'echo X >> settings.local.json', 'ask', 'allow', 'allow'),
    ('A echo >> scripts/x.sh', 'alt', 'Bash', 'echo X >> scripts/x.sh', 'allow', 'allow', 'allow'),
    ('AH Write harness/hooks/x.py', 'althome', 'Write', 'harness/hooks/x.py', 'ask', 'allow', 'ask'),
    ('AH Write harness/scripts/x.sh', 'althome', 'Write', 'harness/scripts/x.sh', 'ask', 'allow', 'allow'),
    ('AH echo >> harness/settings.json', 'althome', 'Bash', 'echo X >> harness/settings.json', 'ask', 'ask', 'ask'),
    ('AH echo >> harness/CLAUDE.md', 'althome', 'Bash', 'echo X >> harness/CLAUDE.md', 'ask', 'allow', 'allow'),
    ('M Write .config/claude/protected-runtime.json', 'home', 'Write', '.config/claude/protected-runtime.json', 'n/a', 'n/a', 'n/a'),
    ('M Write .local/bin/git', 'home', 'Write', '.local/bin/git', 'ask', 'allow', 'ask'),
    ('M Write .config/git/config', 'home', 'Write', '.config/git/config', 'ask', 'ask', 'ask'),
    ('M Write .bash_profile', 'home', 'Write', '.bash_profile', 'ask', 'ask', 'ask'),
    ('M Write .zshrc', 'home', 'Write', '.zshrc', 'ask', 'ask', 'ask'),
    ('M Write .npmrc', 'home', 'Write', '.npmrc', 'ask', 'ask', 'ask'),
    ('M Write .config/systemd/user/x.service', 'home', 'Write', '.config/systemd/user/x.service', 'ask', 'allow', 'ask'),
    ('M Write .ssh/config', 'home', 'Write', '.ssh/config', 'ask', 'allow', 'ask'),
    ('M Write .gnupg/gpg.conf', 'home', 'Write', '.gnupg/gpg.conf', 'ask', 'allow', 'ask'),
    ('M Write .pypirc', 'home', 'Write', '.pypirc', 'ask', 'allow', 'ask'),
    ('M Write .netrc', 'home', 'Write', '.netrc', 'ask', 'allow', 'ask'),
    ('M Write .docker/config.json', 'home', 'Write', '.docker/config.json', 'ask', 'allow', 'ask'),
    ('M Write .kube/config', 'home', 'Write', '.kube/config', 'ask', 'allow', 'ask'),
    ('M Write .config/autostart/x.desktop', 'home', 'Write', '.config/autostart/x.desktop', 'ask', 'allow', 'ask'),
    ('M echo >> .config/claude/protected-runtime.json', 'home', 'Bash', 'echo X >> .config/claude/protected-runtime.json', 'ask', 'allow', 'allow'),
    ('A sed -i hooks/pretool-launch.py', 'alt', 'Bash', "sed -i 's/# hook/X/' hooks/pretool-launch.py", 'allow', 'allow', 'allow'),
    ('A echo >> hooks/pretool-launch.py', 'alt', 'Bash', 'echo X >> hooks/pretool-launch.py', 'ask', 'allow', 'allow'),
    ('A tee -a CLAUDE.md', 'alt', 'Bash', 'echo X | tee -a CLAUDE.md', 'allow', 'allow', 'allow'),
    ('AH echo >> harness/hooks/pretool-launch.py', 'althome', 'Bash', 'echo X >> harness/hooks/pretool-launch.py', 'ask', 'allow', 'allow'),
    ('M sed -i .config/claude/protected-runtime.json', 'home', 'Bash', "sed -i 's/{}/X/' .config/claude/protected-runtime.json", 'allow', 'allow', 'allow'),
    ('H sed -i hooks/pretool-launch.py (default install)', 'harness', 'Bash', "sed -i 's/# hook/X/' hooks/pretool-launch.py", 'ask', 'ask', 'ask'),
    ('P sed -i src file (control)', 'proj', 'Bash', "printf 'a\\n' > src/a.py; sed -i 's/a/X/' src/a.py", 'ask', 'allow', 'allow'),
    ('A Write agents/x.md', 'alt', 'Write', 'agents/x.md', 'ask', 'allow', 'ask'),
    ('A Write commands/x.md', 'alt', 'Write', 'commands/x.md', 'ask', 'allow', 'ask'),
    ('A Write skills/x/SKILL.md', 'alt', 'Write', 'skills/x/SKILL.md', 'ask', 'allow', 'ask'),
    ('A Write schemas/x.json', 'alt', 'Write', 'schemas/x.json', 'ask', 'allow', 'ask'),
    ('A Write settings.machine.json', 'alt', 'Write', 'settings.machine.json', 'ask', 'allow', 'ask'),
    ('A Write settings.local.json', 'alt', 'Write', 'settings.local.json', 'ask', 'allow', 'ask'),
    ('A Write docs/x.md (base allow)', 'alt', 'Write', 'docs/x.md', 'allow', 'allow', 'allow'),
    ('A Write tests/generated/x.py (base allow)', 'alt', 'Write', 'tests/generated/x.py', 'allow', 'allow', 'allow'),
    ('AH Write harness/policies/x.json', 'althome', 'Write', 'harness/policies/x.json', 'ask', 'allow', 'ask'),
    ('H Write hooks/x.py (default install, cwd=~/.claude)', 'harness', 'Write', 'hooks/x.py', 'ask', 'ask', 'ask'),
    ('HM Write .claude/hooks/x.py (cwd=home)', 'home', 'Write', '.claude/hooks/x.py', 'deny', 'deny', 'deny'),
    ('HM echo > .claude/settings.json (cwd=home)', 'home', 'Bash', 'echo X > .claude/settings.json', 'deny', 'deny', 'deny'),
    ('HM Write .claude/settings.json (cwd=home)', 'home', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('HM Write .claude/.harness-switch/off (cwd=home)', 'home', 'Write', '.claude/.harness-switch/off', 'deny', 'deny', 'deny'),
    ('HM Write .env (cwd=home)', 'home', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('HM Write proj/.github/x.yml (cwd=home)', 'home', 'Write', 'proj/.github/x.yml', 'ask', 'allow', 'allow'),
    ('HM Write notes.md (cwd=home)', 'home', 'Write', 'notes.md', 'ask', 'allow', 'allow'),
    ('HM Write .review/x.md (cwd=home, base allow)', 'home', 'Write', '.review/x.md', 'allow', 'allow', 'allow'),
    ('HM Write .config/x/package.json (cwd=home, base allow)', 'home', 'Write', '.config/x/package.json', 'allow', 'allow', 'ask'),
    ('HM Write .ssh/authorized_keys', 'home', 'Write', '.ssh/authorized_keys', 'ask', 'allow', 'ask'),
    ('HM echo >> .ssh/authorized_keys', 'home', 'Bash', 'echo X >> .ssh/authorized_keys', 'ask', 'allow', 'allow'),
    ('HM Write .aws/credentials', 'home', 'Write', '.aws/credentials', 'deny', 'deny', 'deny'),
    ('P Write .github/workflows/x.yml', 'proj', 'Write', '.github/workflows/x.yml', 'ask', 'allow', 'allow'),
    ('P Write docs/x.md', 'proj', 'Write', 'docs/x.md', 'allow', 'allow', 'allow'),
    ('P Write scripts/x.sh', 'proj', 'Write', 'scripts/x.sh', 'allow', 'allow', 'allow'),
    ('P Write .review/x.md', 'proj', 'Write', '.review/x.md', 'allow', 'allow', 'allow'),
    ('P Write package.json', 'proj', 'Write', 'package.json', 'allow', 'allow', 'allow'),
    ('P Write hooks/x.py (project dir)', 'proj', 'Write', 'hooks/x.py', 'ask', 'allow', 'allow'),
    ('P Write CLAUDE.md (project)', 'proj', 'Write', 'CLAUDE.md', 'ask', 'allow', 'allow'),
    ('P Write settings.json (project root)', 'proj', 'Write', 'settings.json', 'ask', 'allow', 'allow'),
    ('S sudo tee .claude/settings.json', 'proj', 'Bash', 'echo X | sudo tee .claude/settings.json', 'deny', 'deny', 'deny'),
    ('S sudo tee .claude/hooks/x.sh', 'proj', 'Bash', 'echo X | sudo tee .claude/hooks/x.sh', 'deny', 'deny', 'deny'),
    ('S sudo tee .env', 'proj', 'Bash', 'echo X | sudo tee .env', 'deny', 'deny', 'deny'),
    ('S sudo tee .ssh/config (cwd=home)', 'home', 'Bash', 'echo X | sudo tee .ssh/config', 'deny', 'deny', 'deny'),
    ('S sudo tee harness/hooks/x.py (alt, cwd=home)', 'althome', 'Bash', 'echo X | sudo tee harness/hooks/x.py', 'deny', 'deny', 'deny'),
    ('S sudo tee .claude/.harness-switch/off (cwd=home)', 'home', 'Bash', 'echo X | sudo tee .claude/.harness-switch/off', 'deny', 'deny', 'deny'),
    ('S tee .claude/.harness-switch/off (cwd=home)', 'home', 'Bash', 'echo X | tee .claude/.harness-switch/off', 'deny', 'deny', 'deny'),
    ('P echo > docs/x.md (base allow)', 'proj', 'Bash', 'echo X > docs/x.md', 'allow', 'allow', 'allow'),
    ('P echo > scripts/x.sh (base allow)', 'proj', 'Bash', 'echo X > scripts/x.sh', 'allow', 'allow', 'allow'),
    ('P echo > .review/x.md (base allow)', 'proj', 'Bash', 'echo X > .review/x.md', 'allow', 'allow', 'allow'),
    ('P echo > docs/hooks/x.md (base allow)', 'proj', 'Bash', 'echo X > docs/hooks/x.md', 'allow', 'allow', 'allow'),
    ('P echo > package.json (base allow)', 'proj', 'Bash', 'echo X > package.json', 'allow', 'allow', 'allow'),
    ('P echo > src/.gitignore', 'proj', 'Bash', 'echo X > src/.gitignore', 'ask', 'allow', 'allow'),
    ('P echo > ./notes.md', 'proj', 'Bash', 'echo X > ./notes.md', 'ask', 'allow', 'allow'),
    ('P grep arrow ./.github (read-only, no redirect)', 'proj', 'Bash', "grep -rn '->' ./src || true", 'other', 'other', 'other'),
    ('P echo 2>&1 out', 'proj', 'Bash', 'echo X > out.txt 2>&1', 'ask', 'allow', 'allow'),
    ('A echo > scripts/x.sh (base allow)', 'alt', 'Bash', 'echo X > scripts/x.sh', 'allow', 'allow', 'allow'),
    ('A echo > docs/x.md (base allow)', 'alt', 'Bash', 'echo X > docs/x.md', 'allow', 'allow', 'allow'),
    ('A echo >> policies/x.json', 'alt', 'Bash', 'echo X >> policies/x.json', 'ask', 'allow', 'allow'),
    ('A echo >> agents/x.md', 'alt', 'Bash', 'echo X >> agents/x.md', 'ask', 'allow', 'allow'),
    ('A echo >> settings.machine.json', 'alt', 'Bash', 'echo X >> settings.machine.json', 'ask', 'allow', 'allow'),
    ('A echo > new.md', 'alt', 'Bash', 'echo X > new.md', 'ask', 'allow', 'allow'),
    ('HM echo >> ~/.ssh/config (tilde)', 'home', 'Bash', 'echo X >> ~/.ssh/config', 'ask', 'ask', 'ask'),
    ('HM echo >> $HOME/.netrc', 'home', 'Bash', 'echo X >> $HOME/.netrc', 'ask', 'ask', 'ask'),
    ('HM echo >> .config/systemd/user/x.service', 'home', 'Bash', 'echo X >> .config/systemd/user/x.service', 'ask', 'allow', 'allow'),
    ('HM echo >> .local/bin/git', 'home', 'Bash', 'echo X >> .local/bin/git', 'ask', 'allow', 'allow'),
    ('HM echo >> proj/.github/x.yml', 'home', 'Bash', 'echo X >> proj/.github/x.yml', 'ask', 'allow', 'allow'),
    ('HM echo > .claude/settings.json (deny kept)', 'home', 'Bash', 'echo X > .claude/settings.json', 'deny', 'deny', 'deny'),
    ('HM echo > .claude/hooks/x.py (deny kept)', 'home', 'Bash', 'echo X > .claude/hooks/x.py', 'deny', 'deny', 'deny'),
    ('HM echo > .claude/.harness-switch/off (deny kept)', 'home', 'Bash', 'echo X > .claude/.harness-switch/off', 'deny', 'deny', 'deny'),
    ('HM echo > .env (deny kept)', 'home', 'Bash', 'echo X > .env', 'deny', 'deny', 'deny'),
    ('S sudo tee hooks/x.py (alt)', 'alt', 'Bash', 'echo X | sudo tee hooks/x.py', 'deny', 'deny', 'deny'),
    ('S sudo sh -c echo > .claude/settings.json', 'proj', 'Bash', "sudo sh -c 'echo X > .claude/settings.json'", 'deny', 'deny', 'deny'),
]

MEASURED_HOME = [
    ('E alt Edit(/.claude/**)', 'alt', 'Write', '.claude/probe-x.txt', 'ask', 'ask', 'ask'),
    ('E althome Edit(/.claude/**)', 'althome', 'Write', 'harness/.claude/probe-x.txt', 'ask', 'ask', 'ask'),
    ('E alt Edit(/.gitattributes)', 'alt', 'Write', '.gitattributes', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.gitattributes)', 'althome', 'Write', 'harness/.gitattributes', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.github/**)', 'alt', 'Write', '.github/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.github/**)', 'althome', 'Write', 'harness/.github/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.gitignore)', 'alt', 'Write', '.gitignore', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.gitignore)', 'althome', 'Write', 'harness/.gitignore', 'ask', 'allow', 'ask'),
    ('E alt Edit(/AGENTS.md)', 'alt', 'Write', 'AGENTS.md', 'ask', 'allow', 'ask'),
    ('E althome Edit(/AGENTS.md)', 'althome', 'Write', 'harness/AGENTS.md', 'ask', 'allow', 'ask'),
    ('E alt Edit(/ARCHITECTURE.md)', 'alt', 'Write', 'ARCHITECTURE.md', 'ask', 'allow', 'ask'),
    ('E althome Edit(/ARCHITECTURE.md)', 'althome', 'Write', 'harness/ARCHITECTURE.md', 'ask', 'allow', 'ask'),
    ('E alt Edit(/CHANGELOG.md)', 'alt', 'Write', 'CHANGELOG.md', 'ask', 'allow', 'ask'),
    ('E althome Edit(/CHANGELOG.md)', 'althome', 'Write', 'harness/CHANGELOG.md', 'ask', 'allow', 'ask'),
    ('E alt Edit(/CLAUDE.md)', 'alt', 'Write', 'CLAUDE.md', 'n/a', 'n/a', 'n/a'),
    ('E althome Edit(/CLAUDE.md)', 'althome', 'Write', 'harness/CLAUDE.md', 'n/a', 'n/a', 'n/a'),
    ('E alt Edit(/INDEX.md)', 'alt', 'Write', 'INDEX.md', 'ask', 'allow', 'ask'),
    ('E althome Edit(/INDEX.md)', 'althome', 'Write', 'harness/INDEX.md', 'ask', 'allow', 'ask'),
    ('E alt Edit(/LICENSE)', 'alt', 'Write', 'LICENSE', 'ask', 'allow', 'ask'),
    ('E althome Edit(/LICENSE)', 'althome', 'Write', 'harness/LICENSE', 'ask', 'allow', 'ask'),
    ('E alt Edit(/NOTICE)', 'alt', 'Write', 'NOTICE', 'ask', 'allow', 'ask'),
    ('E althome Edit(/NOTICE)', 'althome', 'Write', 'harness/NOTICE', 'ask', 'allow', 'ask'),
    ('E alt Edit(/PUBLIC-CORE.md)', 'alt', 'Write', 'PUBLIC-CORE.md', 'ask', 'allow', 'ask'),
    ('E althome Edit(/PUBLIC-CORE.md)', 'althome', 'Write', 'harness/PUBLIC-CORE.md', 'ask', 'allow', 'ask'),
    ('E alt Edit(/README.md)', 'alt', 'Write', 'README.md', 'ask', 'allow', 'ask'),
    ('E althome Edit(/README.md)', 'althome', 'Write', 'harness/README.md', 'ask', 'allow', 'ask'),
    ('E alt Edit(/VERSION)', 'alt', 'Write', 'VERSION', 'ask', 'allow', 'ask'),
    ('E althome Edit(/VERSION)', 'althome', 'Write', 'harness/VERSION', 'ask', 'allow', 'ask'),
    ('E alt Edit(/agents/**)', 'alt', 'Write', 'agents/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/agents/**)', 'althome', 'Write', 'harness/agents/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/commands/**)', 'alt', 'Write', 'commands/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/commands/**)', 'althome', 'Write', 'harness/commands/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/conftest.py)', 'alt', 'Write', 'conftest.py', 'ask', 'allow', 'ask'),
    ('E althome Edit(/conftest.py)', 'althome', 'Write', 'harness/conftest.py', 'ask', 'allow', 'ask'),
    ('E alt Edit(/examples/**)', 'alt', 'Write', 'examples/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/examples/**)', 'althome', 'Write', 'harness/examples/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/hooks/**)', 'alt', 'Write', 'hooks/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/hooks/**)', 'althome', 'Write', 'harness/hooks/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/policies/**)', 'alt', 'Write', 'policies/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/policies/**)', 'althome', 'Write', 'harness/policies/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/push.sh)', 'alt', 'Write', 'push.sh', 'ask', 'allow', 'ask'),
    ('E althome Edit(/push.sh)', 'althome', 'Write', 'harness/push.sh', 'ask', 'allow', 'ask'),
    ('E alt Edit(/pytest.ini)', 'alt', 'Write', 'pytest.ini', 'ask', 'allow', 'ask'),
    ('E althome Edit(/pytest.ini)', 'althome', 'Write', 'harness/pytest.ini', 'ask', 'allow', 'ask'),
    ('E alt Edit(/release-membership.v1.json)', 'alt', 'Write', 'release-membership.v1.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/release-membership.v1.json)', 'althome', 'Write', 'harness/release-membership.v1.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/requirements/**)', 'alt', 'Write', 'requirements/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/requirements/**)', 'althome', 'Write', 'harness/requirements/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/schemas/**)', 'alt', 'Write', 'schemas/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/schemas/**)', 'althome', 'Write', 'harness/schemas/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/settings*.json)', 'alt', 'Write', 'settings.local.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/settings*.json)', 'althome', 'Write', 'harness/settings.local.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/skills/**)', 'alt', 'Write', 'skills/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/skills/**)', 'althome', 'Write', 'harness/skills/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/templates/**)', 'alt', 'Write', 'templates/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/templates/**)', 'althome', 'Write', 'harness/templates/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tools/**)', 'alt', 'Write', 'tools/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tools/**)', 'althome', 'Write', 'harness/tools/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/*.*)', 'alt', 'Write', 'tests/test_x.py', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/*.*)', 'althome', 'Write', 'harness/tests/test_x.py', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/artifact_graph/**)', 'alt', 'Write', 'tests/artifact_graph/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/artifact_graph/**)', 'althome', 'Write', 'harness/tests/artifact_graph/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/differential/**)', 'alt', 'Write', 'tests/differential/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/differential/**)', 'althome', 'Write', 'harness/tests/differential/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/fixtures/**)', 'alt', 'Write', 'tests/fixtures/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/fixtures/**)', 'althome', 'Write', 'harness/tests/fixtures/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/instructions/**)', 'alt', 'Write', 'tests/instructions/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/instructions/**)', 'althome', 'Write', 'harness/tests/instructions/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/lint/**)', 'alt', 'Write', 'tests/lint/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/lint/**)', 'althome', 'Write', 'harness/tests/lint/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/replay/**)', 'alt', 'Write', 'tests/replay/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/replay/**)', 'althome', 'Write', 'harness/tests/replay/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/scripts/**)', 'alt', 'Write', 'tests/scripts/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/scripts/**)', 'althome', 'Write', 'harness/tests/scripts/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/shell_parse/**)', 'alt', 'Write', 'tests/shell_parse/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/shell_parse/**)', 'althome', 'Write', 'harness/tests/shell_parse/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/__pycache__/**)', 'alt', 'Write', 'tests/__pycache__/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/__pycache__/**)', 'althome', 'Write', 'harness/tests/__pycache__/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tests/reports/**)', 'alt', 'Write', 'tests/reports/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tests/reports/**)', 'althome', 'Write', 'harness/tests/reports/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/venv/**)', 'alt', 'Write', 'venv/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/venv/**)', 'althome', 'Write', 'harness/venv/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.venv/**)', 'alt', 'Write', '.venv/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.venv/**)', 'althome', 'Write', 'harness/.venv/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/env/**)', 'alt', 'Write', 'env/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/env/**)', 'althome', 'Write', 'harness/env/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/node_modules/**)', 'alt', 'Write', 'node_modules/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/node_modules/**)', 'althome', 'Write', 'harness/node_modules/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/__pycache__/**)', 'alt', 'Write', '__pycache__/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/__pycache__/**)', 'althome', 'Write', 'harness/__pycache__/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/todos/**)', 'alt', 'Write', 'todos/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/todos/**)', 'althome', 'Write', 'harness/todos/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/shell-snapshots/**)', 'alt', 'Write', 'shell-snapshots/probe-x.txt', 'refused', 'refused', 'refused'),
    ('E althome Edit(/shell-snapshots/**)', 'althome', 'Write', 'harness/shell-snapshots/probe-x.txt', 'refused', 'refused', 'refused'),
    ('E alt Edit(/debug/**)', 'alt', 'Write', 'debug/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/debug/**)', 'althome', 'Write', 'harness/debug/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/plugins/**)', 'alt', 'Write', 'plugins/probe-x.txt', 'ask', 'ask', 'ask'),
    ('E althome Edit(/plugins/**)', 'althome', 'Write', 'harness/plugins/probe-x.txt', 'ask', 'ask', 'ask'),
    ('E alt Edit(/statsig/**)', 'alt', 'Write', 'statsig/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/statsig/**)', 'althome', 'Write', 'harness/statsig/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/logs/**)', 'alt', 'Write', 'logs/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/logs/**)', 'althome', 'Write', 'harness/logs/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/session-env/**)', 'alt', 'Write', 'session-env/probe-x.txt', 'refused', 'refused', 'refused'),
    ('E althome Edit(/session-env/**)', 'althome', 'Write', 'harness/session-env/probe-x.txt', 'refused', 'refused', 'refused'),
    ('E alt Edit(/file-history/**)', 'alt', 'Write', 'file-history/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/file-history/**)', 'althome', 'Write', 'harness/file-history/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/sessions/**)', 'alt', 'Write', 'sessions/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/sessions/**)', 'althome', 'Write', 'harness/sessions/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/attribution-seals/**)', 'alt', 'Write', 'attribution-seals/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/attribution-seals/**)', 'althome', 'Write', 'harness/attribution-seals/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/dev-registry/**)', 'alt', 'Write', 'dev-registry/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/dev-registry/**)', 'althome', 'Write', 'harness/dev-registry/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/dev-start-replays/**)', 'alt', 'Write', 'dev-start-replays/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/dev-start-replays/**)', 'althome', 'Write', 'harness/dev-start-replays/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/paseo-daemon/**)', 'alt', 'Write', 'paseo-daemon/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/paseo-daemon/**)', 'althome', 'Write', 'harness/paseo-daemon/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/scratch/**)', 'alt', 'Write', 'scratch/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/scratch/**)', 'althome', 'Write', 'harness/scratch/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/session-resources/**)', 'alt', 'Write', 'session-resources/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/session-resources/**)', 'althome', 'Write', 'harness/session-resources/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/specs/**)', 'alt', 'Write', 'specs/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/specs/**)', 'althome', 'Write', 'harness/specs/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/state/**)', 'alt', 'Write', 'state/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/state/**)', 'althome', 'Write', 'harness/state/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/archive/**)', 'alt', 'Write', 'archive/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/archive/**)', 'althome', 'Write', 'harness/archive/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/backups/**)', 'alt', 'Write', 'backups/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/backups/**)', 'althome', 'Write', 'harness/backups/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/cache/**)', 'alt', 'Write', 'cache/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/cache/**)', 'althome', 'Write', 'harness/cache/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/paste-cache/**)', 'alt', 'Write', 'paste-cache/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/paste-cache/**)', 'althome', 'Write', 'harness/paste-cache/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/restart-state/**)', 'alt', 'Write', 'restart-state/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/restart-state/**)', 'althome', 'Write', 'harness/restart-state/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/tasks/**)', 'alt', 'Write', 'tasks/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/tasks/**)', 'althome', 'Write', 'harness/tasks/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/graphify-out/**)', 'alt', 'Write', 'graphify-out/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/graphify-out/**)', 'althome', 'Write', 'harness/graphify-out/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.playwright-mcp/**)', 'alt', 'Write', '.playwright-mcp/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.playwright-mcp/**)', 'althome', 'Write', 'harness/.playwright-mcp/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/worktrees/**)', 'alt', 'Write', 'worktrees/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/worktrees/**)', 'althome', 'Write', 'harness/worktrees/probe-x.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.credentials.json)', 'alt', 'Write', '.credentials.json', 'refused', 'refused', 'refused'),
    ('E althome Edit(/.credentials.json)', 'althome', 'Write', 'harness/.credentials.json', 'refused', 'refused', 'refused'),
    ('E alt Edit(/private-literals.txt)', 'alt', 'Write', 'private-literals.txt', 'ask', 'allow', 'ask'),
    ('E althome Edit(/private-literals.txt)', 'althome', 'Write', 'harness/private-literals.txt', 'ask', 'allow', 'ask'),
    ('E alt Edit(/history.jsonl)', 'alt', 'Write', 'history.jsonl', 'ask', 'allow', 'ask'),
    ('E althome Edit(/history.jsonl)', 'althome', 'Write', 'harness/history.jsonl', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.doc-sync-cache.json)', 'alt', 'Write', '.doc-sync-cache.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.doc-sync-cache.json)', 'althome', 'Write', 'harness/.doc-sync-cache.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/mcp-needs-auth-cache.json)', 'alt', 'Write', 'mcp-needs-auth-cache.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/mcp-needs-auth-cache.json)', 'althome', 'Write', 'harness/mcp-needs-auth-cache.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.last-cleanup)', 'alt', 'Write', '.last-cleanup', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.last-cleanup)', 'althome', 'Write', 'harness/.last-cleanup', 'ask', 'allow', 'ask'),
    ('E alt Edit(/playwright-storage-state.json)', 'alt', 'Write', 'playwright-storage-state.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/playwright-storage-state.json)', 'althome', 'Write', 'harness/playwright-storage-state.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/agent-scores.json)', 'alt', 'Write', 'agent-scores.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/agent-scores.json)', 'althome', 'Write', 'harness/agent-scores.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/agent-scores.json.lock)', 'alt', 'Write', 'agent-scores.json.lock', 'ask', 'allow', 'ask'),
    ('E althome Edit(/agent-scores.json.lock)', 'althome', 'Write', 'harness/agent-scores.json.lock', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.hook-refactor-allow)', 'alt', 'Write', '.hook-refactor-allow', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.hook-refactor-allow)', 'althome', 'Write', 'harness/.hook-refactor-allow', 'ask', 'allow', 'ask'),
    ('E alt Edit(/overnight-*)', 'alt', 'Write', 'overnight-state-x.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/overnight-*)', 'althome', 'Write', 'harness/overnight-state-x.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/workflow-*)', 'alt', 'Write', 'workflow-x.json', 'ask', 'allow', 'ask'),
    ('E althome Edit(/workflow-*)', 'althome', 'Write', 'harness/workflow-x.json', 'ask', 'allow', 'ask'),
    ('E alt Edit(/.settings.render.*)', 'alt', 'Write', '.settings.render.x', 'ask', 'allow', 'ask'),
    ('E althome Edit(/.settings.render.*)', 'althome', 'Write', 'harness/.settings.render.x', 'ask', 'allow', 'ask'),
    ('E alt Edit(/*.bak-*)', 'alt', 'Write', 'a.bak-1', 'ask', 'allow', 'ask'),
    ('E althome Edit(/*.bak-*)', 'althome', 'Write', 'harness/a.bak-1', 'ask', 'allow', 'ask'),
    ('E alt Edit(/settings.json.backup.*)', 'alt', 'Write', 'settings.json.backup.1', 'ask', 'allow', 'ask'),
    ('E althome Edit(/settings.json.backup.*)', 'althome', 'Write', 'harness/settings.json.backup.1', 'ask', 'allow', 'ask'),
    ('E alt Edit(/*.png)', 'alt', 'Write', 'a.png', 'ask', 'allow', 'ask'),
    ('E althome Edit(/*.png)', 'althome', 'Write', 'harness/a.png', 'ask', 'allow', 'ask'),
    ('E alt Edit(/projects/**/*.jsonl)', 'alt', 'Write', 'projects/p/s.jsonl', 'ask', 'allow', 'ask'),
    ('E althome Edit(/projects/**/*.jsonl)', 'althome', 'Write', 'harness/projects/p/s.jsonl', 'ask', 'allow', 'ask'),
    ('K alt residual docs/x.md', 'alt', 'Write', 'docs/x.md', 'allow', 'allow', 'allow'),
    ('K alt residual scripts/x.sh', 'alt', 'Write', 'scripts/x.sh', 'allow', 'allow', 'allow'),
    ('K alt residual requirements.txt', 'alt', 'Write', 'requirements.txt', 'allow', 'allow', 'allow'),
    ('K alt residual tests/generated/x.py', 'alt', 'Write', 'tests/generated/x.py', 'allow', 'allow', 'allow'),
    ('K alt overlap hooks/package.json', 'alt', 'Write', 'hooks/package.json', 'allow', 'allow', 'ask'),
    ('K alt overlap tools/x/pyproject.toml', 'alt', 'Write', 'tools/x/pyproject.toml', 'allow', 'allow', 'ask'),
    ('K alt memory md', 'alt', 'Write', 'projects/{ENC}/memory/note.md', 'allow', 'allow', 'allow'),
    ('K proj default-install memory md', 'proj', 'Write', '../.claude/projects/{ENC}/memory/note.md', 'allow', 'allow', 'allow'),
    ('K alt deny .claude/settings.json', 'alt', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('K alt deny .claude/hooks/x.sh', 'alt', 'Write', '.claude/hooks/x.sh', 'deny', 'deny', 'deny'),
    ('K alt deny .claude/settings.local.json', 'alt', 'Write', '.claude/settings.local.json', 'ask', 'deny', 'deny'),
    ('K alt deny .harness-switch/off', 'alt', 'Write', '.harness-switch/off', 'deny', 'deny', 'deny'),
    ('K alt deny .env', 'alt', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('K alt deny x.key', 'alt', 'Write', 'x.key', 'deny', 'deny', 'deny'),
    ('K alt deny sudo tee .claude/settings.json', 'alt', 'Bash', 'echo X | sudo tee .claude/settings.json', 'deny', 'deny', 'deny'),
    ('K proj project write src/newmodule.py', 'proj', 'Write', 'src/newmodule.py', 'ask', 'allow', 'allow'),
    ('K proj project heredoc', 'proj', 'Bash', "cat > notes.md <<'EOF'\nX\nEOF", 'ask', 'allow', 'allow'),
    ('A Write venv sitecustomize', 'alt', 'Write', 'venv/lib/python3.13/site-packages/sitecustomize.py', 'ask', 'allow', 'ask'),
    ('A Write templates/prompt-includes/y.md', 'alt', 'Write', 'templates/prompt-includes/y.md', 'ask', 'allow', 'ask'),
    ('A Write private-literals.txt', 'alt', 'Write', 'private-literals.txt', 'ask', 'allow', 'ask'),
    ('A Write requirements/py313.txt', 'alt', 'Write', 'requirements/py313.txt', 'ask', 'allow', 'ask'),
    ('A Write hooks/lib/y.py', 'alt', 'Write', 'hooks/lib/y.py', 'ask', 'allow', 'ask'),
    ('A Write .git/hooks/pre-push', 'alt', 'Write', '.git/hooks/pre-push', 'ask', 'ask', 'ask'),
    ('A Write settings.machine.json', 'alt', 'Write', 'settings.machine.json', 'ask', 'allow', 'ask'),
    ('H Write venv sitecustomize (default)', 'harness', 'Write', 'venv/lib/python3.13/site-packages/sitecustomize.py', 'ask', 'ask', 'ask'),
    ('D K proj default-install memory md', 'proj', 'Write', '../.claude/projects/{ENC}/memory/note.md', 'allow', 'allow', 'allow'),
    ('D K proj default-install plan md', 'proj', 'Write', '../.claude/plans/p.md', 'ask', 'ask', 'ask'),
    ('D M Write .ssh/config', 'home', 'Write', '.ssh/config', 'ask', 'allow', 'ask'),
    ('D M Write .netrc', 'home', 'Write', '.netrc', 'ask', 'allow', 'ask'),
    ('D M Write .pypirc', 'home', 'Write', '.pypirc', 'ask', 'allow', 'ask'),
    ('D M Write .local/bin/git', 'home', 'Write', '.local/bin/git', 'ask', 'allow', 'ask'),
    ('D M Write .config/systemd/user/x.service', 'home', 'Write', '.config/systemd/user/x.service', 'ask', 'allow', 'ask'),
    ('D M Write .claude/x.md (cwd=home)', 'home', 'Write', '.claude/x.md', 'ask', 'ask', 'ask'),
    ('D M Write .newtool/config (cwd=home)', 'home', 'Write', '.newtool/config', 'ask', 'allow', 'ask'),
    ('D K alt memory md', 'alt', 'Write', 'projects/{ENC}/memory/note.md', 'allow', 'allow', 'allow'),
    ('D M Write .docker/config.json', 'home', 'Write', '.docker/config.json', 'ask', 'allow', 'ask'),
    ('D M Write .gnupg/gpg.conf', 'home', 'Write', '.gnupg/gpg.conf', 'ask', 'allow', 'ask'),
    ('D M Write .kube/config', 'home', 'Write', '.kube/config', 'ask', 'allow', 'ask'),
    ('D M Write .ab (cwd=home)', 'home', 'Write', '.ab', 'ask', 'allow', 'ask'),
    ('D M Write .mozilla/x (7)', 'home', 'Write', '.mozilla/x', 'ask', 'allow', 'ask'),
    ('D M Write .claudex/x (7)', 'home', 'Write', '.claudex/x', 'ask', 'allow', 'ask'),
    ('D M Write .claude.json.x', 'home', 'Write', '.claude.json.x', 'ask', 'allow', 'ask'),
    ('D HM Write proj/.gh/x.yml', 'home', 'Write', 'proj/.gh/x.yml', 'ask', 'allow', 'allow'),
    ('D HM Write notes.md', 'home', 'Write', 'notes.md', 'ask', 'allow', 'allow'),
    ('D HM Write .review/x.md', 'home', 'Write', '.review/x.md', 'allow', 'allow', 'allow'),
    ('D HM Write .env', 'home', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('D HM Write .claude/settings.json', 'home', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('D HM Write .claude/hooks/x.py', 'home', 'Write', '.claude/hooks/x.py', 'deny', 'deny', 'deny'),
    ('V A Write venv/lib/python3.13/site-packages/zz.pth', 'alt', 'Write', 'venv/lib/python3.13/site-packages/zz.pth', 'ask', 'allow', 'ask'),
    ('V A Write templates/prompt-includes/y.md', 'alt', 'Write', 'templates/prompt-includes/y.md', 'ask', 'allow', 'ask'),
    ('V A Write requirements/py313.txt', 'alt', 'Write', 'requirements/py313.txt', 'ask', 'allow', 'ask'),
    ('V A Write private-literals.txt', 'alt', 'Write', 'private-literals.txt', 'ask', 'allow', 'ask'),
    ('V A Write tools/x.py', 'alt', 'Write', 'tools/x.py', 'ask', 'allow', 'ask'),
    ('V A Write hooks/x.py', 'alt', 'Write', 'hooks/x.py', 'ask', 'allow', 'ask'),
    ('V A Write policies/x.json', 'alt', 'Write', 'policies/x.json', 'ask', 'allow', 'ask'),
    ('V A Write new.md', 'alt', 'Write', 'new.md', 'ask', 'allow', 'allow'),
    ('V A Write .claude.json', 'alt', 'Write', '.claude.json', 'n/a', 'n/a', 'n/a'),
    ('V A Write rules/x.md', 'alt', 'Write', 'rules/x.md', 'ask', 'allow', 'ask'),
    ('V A Write output-styles/x.md', 'alt', 'Write', 'output-styles/x.md', 'ask', 'allow', 'ask'),
    ('V A Write keybindings.json', 'alt', 'Write', 'keybindings.json', 'ask', 'allow', 'ask'),
    ('V A Write plans/x.md', 'alt', 'Write', 'plans/x.md', 'ask', 'allow', 'allow'),
    ('V A Write projects/-p/memory/MEMORY.md', 'alt', 'Write', 'projects/-p/memory/MEMORY.md', 'ask', 'allow', 'allow'),
    ('V A Write projects/-p/x.jsonl', 'alt', 'Write', 'projects/-p/x.jsonl', 'ask', 'allow', 'ask'),
    ('V A Write agents/x.md', 'alt', 'Write', 'agents/x.md', 'ask', 'allow', 'ask'),
    ('V A Write scripts/x.sh', 'alt', 'Write', 'scripts/x.sh', 'allow', 'allow', 'allow'),
    ('V A Write docs/x.md', 'alt', 'Write', 'docs/x.md', 'allow', 'allow', 'allow'),
    ('V A Write CLAUDE.local.md', 'alt', 'Write', 'CLAUDE.local.md', 'ask', 'allow', 'ask'),
    ('V A Write memory/x.md', 'alt', 'Write', 'memory/x.md', 'ask', 'allow', 'ask'),
    ('V A Write state/x.json', 'alt', 'Write', 'state/x.json', 'ask', 'allow', 'ask'),
    ('V AH Write harness/rules/x.md', 'althome', 'Write', 'harness/rules/x.md', 'ask', 'allow', 'ask'),
    ('V AH Write harness/venv/x.pth', 'althome', 'Write', 'harness/venv/lib/python3.13/site-packages/zz.pth', 'ask', 'allow', 'ask'),
    ('V M Write .ssh/authorized_keys', 'home', 'Write', '.ssh/authorized_keys', 'ask', 'allow', 'ask'),
    ('V M Write .bashrc', 'home', 'Write', '.bashrc', 'n/a', 'n/a', 'n/a'),
    ('V M Write .yarnrc', 'home', 'Write', '.yarnrc', 'ask', 'ask', 'ask'),
    ('V M Write .bundle/config', 'home', 'Write', '.bundle/config', 'ask', 'allow', 'ask'),
    ('V M Write .pulumi/credentials.json', 'home', 'Write', '.pulumi/credentials.json', 'deny', 'deny', 'deny'),
    ('V M Write .rhosts', 'home', 'Write', '.rhosts', 'ask', 'allow', 'ask'),
    ('V M Write .shosts', 'home', 'Write', '.shosts', 'ask', 'allow', 'ask'),
    ('V M Write .tcshrc', 'home', 'Write', '.tcshrc', 'ask', 'allow', 'ask'),
    ('V M Write .nanorc', 'home', 'Write', '.nanorc', 'ask', 'allow', 'ask'),
    ('V M Write .cursor/mcp.json', 'home', 'Write', '.cursor/mcp.json', 'ask', 'allow', 'ask'),
    ('V M Write .gemini/settings.json', 'home', 'Write', '.gemini/settings.json', 'ask', 'allow', 'ask'),
    ('V M Write .my.cnf', 'home', 'Write', '.my.cnf', 'ask', 'allow', 'ask'),
    ('V M Write .local/bin/git', 'home', 'Write', '.local/bin/git', 'ask', 'allow', 'ask'),
    ('V M Write .netrc', 'home', 'Write', '.netrc', 'ask', 'allow', 'ask'),
    ('V M Write .gnupg/gpg.conf', 'home', 'Write', '.gnupg/gpg.conf', 'ask', 'allow', 'ask'),
    ('V M Write .aws/config', 'home', 'Write', '.aws/config', 'ask', 'allow', 'ask'),
    ('V M Write .kube/config', 'home', 'Write', '.kube/config', 'ask', 'allow', 'ask'),
    ('V M Write .cargo/config.toml', 'home', 'Write', '.cargo/config.toml', 'ask', 'ask', 'ask'),
    ('V M Write .zshrc', 'home', 'Write', '.zshrc', 'ask', 'ask', 'ask'),
    ('V M Write .profile', 'home', 'Write', '.profile', 'ask', 'ask', 'ask'),
    ('V M Write .npmrc', 'home', 'Write', '.npmrc', 'ask', 'ask', 'ask'),
    ('V M Write .config/systemd/user/x.service', 'home', 'Write', '.config/systemd/user/x.service', 'ask', 'allow', 'ask'),
    ('V M Write .envrc', 'home', 'Write', '.envrc', 'ask', 'ask', 'ask'),
    ('V M Write .forward', 'home', 'Write', '.forward', 'ask', 'allow', 'ask'),
    ('V M Write .codex/config.toml', 'home', 'Write', '.codex/config.toml', 'ask', 'allow', 'ask'),
    ('V M Write .claude/projects/-p/memory/MEMORY.md', 'home', 'Write', '.claude/projects/-p/memory/MEMORY.md', 'ask', 'ask', 'ask'),
    ('V M Write .claude/plans/x.md', 'home', 'Write', '.claude/plans/x.md', 'ask', 'ask', 'ask'),
    ('V M Write .claude/rules/x.md', 'home', 'Write', '.claude/rules/x.md', 'ask', 'ask', 'ask'),
    ('V M Write .claude/x.md', 'home', 'Write', '.claude/x.md', 'ask', 'ask', 'ask'),
    ('V M Write .m2/settings.xml', 'home', 'Write', '.m2/settings.xml', 'ask', 'allow', 'ask'),
    ('V M Write .pip/pip.conf', 'home', 'Write', '.pip/pip.conf', 'ask', 'allow', 'ask'),
    ('V M Write .condarc', 'home', 'Write', '.condarc', 'ask', 'allow', 'ask'),
    ('V M Write .gitconfig', 'home', 'Write', '.gitconfig', 'n/a', 'n/a', 'n/a'),
    ('V M Write .git-credentials', 'home', 'Write', '.git-credentials', 'ask', 'allow', 'ask'),
    ('V P Write src/newmodule.py', 'proj', 'Write', 'src/newmodule.py', 'ask', 'allow', 'allow'),
    ('V P echo > notes.md', 'proj', 'Bash', 'echo X > notes.md', 'ask', 'allow', 'allow'),
    ('V P heredoc', 'proj', 'Bash', "cat > src/gen.py <<'EOF'\nX\nEOF", 'ask', 'allow', 'allow'),
    ('V P Write .claude/worktrees/a/src/x.py', 'proj', 'Write', '.claude/worktrees/a/src/x.py', 'ask', 'allow', 'allow'),
    ('V P Write package.json', 'proj', 'Write', 'package.json', 'allow', 'allow', 'allow'),
    ('V P Write .env (deny)', 'proj', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('V P Write .claude/settings.json (deny)', 'proj', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('V P Write .claude/hooks/x.sh (deny)', 'proj', 'Write', '.claude/hooks/x.sh', 'deny', 'deny', 'deny'),
    ('V P sudo tee .claude/settings.json', 'proj', 'Bash', 'echo X | sudo tee .claude/settings.json', 'deny', 'deny', 'deny'),
    ('V M Write .aws/credentials (deny)', 'home', 'Write', '.aws/credentials', 'deny', 'deny', 'deny'),
    ('V M Write .env (deny)', 'home', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('V M Write .claude/settings.json (deny)', 'home', 'Write', '.claude/settings.json', 'deny', 'deny', 'deny'),
    ('V M Write .claude/hooks/x.py (deny)', 'home', 'Write', '.claude/hooks/x.py', 'deny', 'deny', 'deny'),
    ('V M Write .harness-switch/x (deny)', 'home', 'Write', '.harness-switch/x', 'deny', 'deny', 'deny'),
    ('V A Write .env (deny)', 'alt', 'Write', '.env', 'deny', 'deny', 'deny'),
    ('V A Write .hook-refactor-allow', 'alt', 'Write', '.hook-refactor-allow', 'ask', 'allow', 'ask'),
    ('V P Write .claude/.hook-refactor-allow', 'proj', 'Write', '.claude/.hook-refactor-allow', 'ask', 'ask', 'ask'),
    ('V M Write .x (1-char ~/.? vs nothing)', 'home', 'Write', '.x', 'ask', 'allow', 'ask'),
    ('N alt Edit(/rules/**)', 'alt', 'Write', 'rules/y.md', 'ask', 'allow', 'ask'),
    ('N althome Edit(/rules/**)', 'althome', 'Write', 'harness/rules/y.md', 'ask', 'allow', 'ask'),
    ('N alt Edit(/output-styles/**)', 'alt', 'Write', 'output-styles/y.md', 'ask', 'allow', 'ask'),
    ('N althome Edit(/output-styles/**)', 'althome', 'Write', 'harness/output-styles/y.md', 'ask', 'allow', 'ask'),
    ('N alt Edit(/themes/**)', 'alt', 'Write', 'themes/y.json', 'ask', 'allow', 'ask'),
    ('N althome Edit(/themes/**)', 'althome', 'Write', 'harness/themes/y.json', 'ask', 'allow', 'ask'),
    ('N alt Edit(/mods/**)', 'alt', 'Write', 'mods/y/index.js', 'ask', 'allow', 'ask'),
    ('N althome Edit(/mods/**)', 'althome', 'Write', 'harness/mods/y/index.js', 'ask', 'allow', 'ask'),
    ('N alt Edit(/dev-mods/**)', 'alt', 'Write', 'dev-mods/y/index.js', 'ask', 'ask', 'ask'),
    ('N althome Edit(/dev-mods/**)', 'althome', 'Write', 'harness/dev-mods/y/index.js', 'ask', 'ask', 'ask'),
    ('N alt Edit(/ide/**)', 'alt', 'Write', 'ide/y.lock', 'ask', 'allow', 'ask'),
    ('N althome Edit(/ide/**)', 'althome', 'Write', 'harness/ide/y.lock', 'ask', 'allow', 'ask'),
    ('N alt Edit(/teams/**)', 'alt', 'Write', 'teams/y.json', 'ask', 'allow', 'ask'),
    ('N althome Edit(/teams/**)', 'althome', 'Write', 'harness/teams/y.json', 'ask', 'allow', 'ask'),
    ('N alt Edit(/memory/**)', 'alt', 'Write', 'memory/y.md', 'ask', 'allow', 'ask'),
    ('N althome Edit(/memory/**)', 'althome', 'Write', 'harness/memory/y.md', 'ask', 'allow', 'ask'),
    ('N alt Edit(/CLAUDE.local.md)', 'alt', 'Write', 'CLAUDE.local.md', 'ask', 'allow', 'ask'),
    ('N althome Edit(/CLAUDE.local.md)', 'althome', 'Write', 'harness/CLAUDE.local.md', 'ask', 'allow', 'ask'),
    ('N alt Edit(/keybindings.json)', 'alt', 'Write', 'keybindings.json', 'ask', 'allow', 'ask'),
    ('N althome Edit(/keybindings.json)', 'althome', 'Write', 'harness/keybindings.json', 'ask', 'allow', 'ask'),
    ('N alt Edit(/statusline*)', 'alt', 'Write', 'statusline.sh', 'ask', 'allow', 'ask'),
    ('N althome Edit(/statusline*)', 'althome', 'Write', 'harness/statusline.sh', 'ask', 'allow', 'ask'),
    ('N alt Edit(/.mcp.json)', 'alt', 'Write', '.mcp.json', 'ask', 'ask', 'ask'),
    ('N althome Edit(/.mcp.json)', 'althome', 'Write', 'harness/.mcp.json', 'ask', 'ask', 'ask'),
    ('N alt Edit(/.claude.json)', 'alt', 'Write', '.claude.json', 'n/a', 'n/a', 'n/a'),
    ('N althome Edit(/.claude.json)', 'althome', 'Write', 'harness/.claude.json', 'n/a', 'n/a', 'n/a'),
    ('N alt Edit(/hooks.json)', 'alt', 'Write', 'hooks.json', 'ask', 'allow', 'ask'),
    ('N althome Edit(/hooks.json)', 'althome', 'Write', 'harness/hooks.json', 'ask', 'allow', 'ask'),
    ('N alt Edit(/remote-settings.json)', 'alt', 'Write', 'remote-settings.json', 'ask', 'ask', 'ask'),
    ('N althome Edit(/remote-settings.json)', 'althome', 'Write', 'harness/remote-settings.json', 'ask', 'ask', 'ask'),
    ('S6 home ~/.bundle', 'home', 'Write', '.bundle/x', 'ask', 'allow', 'ask'),
    ('S6 home ~/.cursor', 'home', 'Write', '.cursor/x', 'ask', 'allow', 'ask'),
    ('S6 home ~/.gemini', 'home', 'Write', '.gemini/x', 'ask', 'allow', 'ask'),
    ('S6 home ~/.my.cnf', 'home', 'Write', '.my.cnf', 'ask', 'allow', 'ask'),
    ('S6 home ~/.nanorc', 'home', 'Write', '.nanorc', 'ask', 'allow', 'ask'),
    ('S6 home ~/.rhosts', 'home', 'Write', '.rhosts', 'ask', 'allow', 'ask'),
    ('S6 home ~/.shosts', 'home', 'Write', '.shosts', 'ask', 'allow', 'ask'),
    ('S6 home ~/.tcshrc', 'home', 'Write', '.tcshrc', 'ask', 'allow', 'ask'),
    ('O alt plans md', 'alt', 'Write', 'plans/p.md', 'ask', 'allow', 'allow'),
    ('O alt workflows js', 'alt', 'Write', 'workflows/w.js', 'ask', 'allow', 'allow'),
    ('O alt jobs tmp', 'alt', 'Write', 'jobs/j1/tmp/a.txt', 'ask', 'allow', 'allow'),
    ('O alt agent-memory md', 'alt', 'Write', 'agent-memory/a/MEMORY.md', 'allow', 'allow', 'allow'),
    ('O alt memory md', 'alt', 'Write', 'projects/{ENC}/memory/note.md', 'allow', 'allow', 'allow'),
    ('O proj default-install memory md', 'proj', 'Write', '../.claude/projects/{ENC}/memory/note.md', 'allow', 'allow', 'allow'),
    ('O proj default-install plan md', 'proj', 'Write', '../.claude/plans/p.md', 'ask', 'ask', 'ask'),
    ('O proj default-install agent-memory md', 'proj', 'Write', '../.claude/agent-memory/a/MEMORY.md', 'allow', 'allow', 'allow'),
    ('O home .review/x.md (base allow)', 'home', 'Write', '.review/x.md', 'allow', 'allow', 'allow'),
    ('O alt docs/x.md (base allow)', 'alt', 'Write', 'docs/x.md', 'allow', 'allow', 'allow'),
    ('O alt scripts/x.sh (base allow)', 'alt', 'Write', 'scripts/x.sh', 'allow', 'allow', 'allow'),
    ('O proj .claude/agents/x.md (base allow path)', 'proj', 'Write', '.claude/agents/x.md', 'ask', 'ask', 'ask'),
]
# Base asked, now allowed, by intent: project writes (the lane's purpose), in a project, a plain clone
# under HOME, or HOME itself for a non-dot path.
PROJECT_WRITES = {
    "P1 Write src/newmodule.py", "P2 echo hi > notes.md", "P3 heredoc > project file", "P4 Write top-level README2.md",
    "K proj project write src/newmodule.py", "K proj project heredoc",
    "C Write hooks/x.py", "C echo >> hooks/x.py", "C echo >> settings.json", "C echo >> CLAUDE.md",
    "P sed -i src file (control)", "HM Write proj/.github/x.yml (cwd=home)", "HM Write notes.md (cwd=home)",
    "D HM Write proj/.gh/x.yml", "D HM Write notes.md",
    "P Write .github/workflows/x.yml", "P Write hooks/x.py (project dir)", "P Write CLAUDE.md (project)",
    "P Write settings.json (project root)", "P echo > src/.gitignore", "P echo > ./notes.md", "P echo 2>&1 out",
    "HM echo >> proj/.github/x.yml",
    "V P Write src/newmodule.py", "V P echo > notes.md", "V P heredoc", "V P Write .claude/worktrees/a/src/x.py",
}
# Base asked, now allowed, owner-accepted: Bash output redirects, which ask rules do not reach.
OPEN_REDIRECTS = {
    "M echo >> .ssh/authorized_keys", "HM echo >> .ssh/authorized_keys", "M echo >> .config/claude/protected-runtime.json",
    "HM echo >> .config/systemd/user/x.service", "HM echo >> .local/bin/git",
    "A echo >> hooks/x.py", "A echo >> CLAUDE.md", "A echo >> settings.local.json", "A echo >> hooks/pretool-launch.py",
    "A echo >> policies/x.json", "A echo >> agents/x.md", "A echo >> settings.machine.json", "A echo > new.md",
    "AH echo >> harness/CLAUDE.md", "AH echo >> harness/hooks/pretool-launch.py",
}
# Base asked, now allowed, residual: `scripts/**` (RESIDUAL: from HOME base asked it, from the clone base allowed it,
# and one anchored ask cannot tell the two apart), a new top-level name neither the harness nor the CLI reads, and
# the CLI_OWNED directories.
OPEN_RESIDUAL = {"AH Write harness/scripts/x.sh", "A Write new.md", "V A Write new.md",
                 # CLI_OWNED: another project's memory, plan files, workflow scripts, background-job scratch
                 "V A Write projects/-p/memory/MEMORY.md", "V A Write plans/x.md", "O alt plans md",
                 "O alt workflows js", "O alt jobs tmp"}
# Base allowed, now asks: a manifest file base allowed anywhere (`Edit(**/package.json)`, ...) inside an asked
# harness-home directory or ~/.config.
ASK_OVERLAP = {"HM Write .config/x/package.json (cwd=home, base allow)", "K alt overlap hooks/package.json",
               "K alt overlap tools/x/pyproject.toml"}


def _permissions() -> dict:
    with open(ROOT / "settings.json", encoding="utf-8") as fh:
        return json.load(fh)["permissions"]


def _anchored_asks() -> list[str]:
    """The settings-source-anchored ask patterns, without `Edit(/` and `)`, a trailing `/**` dropped."""
    out = []
    for rule in _permissions()["ask"]:
        if rule.startswith("Edit(/") and not rule.startswith("Edit(//"):
            body = rule[len("Edit(/"):-1]
            out.append(body[:-3] if body.endswith("/**") else body)
    return out


def _covered(name: str) -> bool:
    if name in RESIDUAL or name in CLI_OWNED or name in OTHERWISE_STOPPED or name in GENERIC:
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in _anchored_asks())


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode()
    return [f for f in out.split("\0") if f]


def test_every_harness_home_entry_is_asked():
    """Each top-level entry of the harness home -- tracked, a runtime entry .gitignore names, or a name the CLI
    reads from its config directory (CLI_READ) -- and each
    entry directly under tests/ is asked at the settings source, or is a named residual. A new top-level
    file or directory fails here until it gets an ask entry or a stated reason."""
    tracked = _tracked()
    missing = []
    for top in sorted({f.split("/")[0] for f in tracked}):
        if top != "tests" and not _covered(top):
            missing.append(top)
    for f in tracked:
        parts = f.split("/")
        if parts[0] == "tests":
            entry = "/".join(parts[:2]) if len(parts) > 2 else f
            if not _covered(entry):
                missing.append(entry)
    for name in CLI_READ:
        if not _covered(name):
            missing.append(name)
    for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        name = line.strip("/")
        if name.endswith("/*"):
            name = name[:-2]
        if name.startswith("tests/"):
            entry = "/".join(name.split("/")[:2])
        elif "/" in name:
            entry = name.split("/")[0]  # below a top-level entry: that entry decides
        else:
            entry = name
        if entry != "tests" and not _covered(entry) and not _covered(line):
            missing.append(line)
    assert not sorted(set(missing)), "harness-home entries with no ask and no stated reason: %s" % sorted(set(missing))


def test_no_home_ask_covers_the_claude_config_dir():
    """The CLI's own writes below ~/.claude (auto-memory) must not prompt: no home ask matches `.claude`."""
    for rule in HOME_ASKS:
        pattern = rule[len("Edit(~/"):-1]
        assert not fnmatch.fnmatchcase(".claude", pattern), rule


def test_the_venv_the_hooks_run_is_asked():
    """hooks/pretool-bash-safety.sh runs the home's venv interpreter; a .pth there runs inside the hook."""
    assert "venv" in _anchored_asks()
    assert "venv/bin/python" in (HOOKS / "pretool-bash-safety.sh").read_text(encoding="utf-8")


def test_the_entries_measured_are_the_entries_shipped():
    perms = _permissions()
    assert perms["ask"] == MEASURED_ASK
    assert perms["ask"][-len(HOME_ASKS):] == HOME_ASKS
    assert "Edit(./**)" in perms["allow"]
    assert "Edit(.claude/settings.local.json)" in perms["deny"]


ALL_ROWS = MEASURED + MEASURED_HOME


@pytest.mark.parametrize("row", ALL_ROWS, ids=[r[0] for r in ALL_ROWS])
def test_no_base_deny_is_downgraded(row):
    label, _cwd, _tool, _arg, base, _first, now = row
    if base == "deny":
        assert now == "deny", label


def test_project_writes_run():
    now = {r[0]: r[6] for r in ALL_ROWS}
    for label in ("P1 Write src/newmodule.py", "P2 echo hi > notes.md", "P3 heredoc > project file",
                  "K proj project write src/newmodule.py", "K proj project heredoc"):
        assert now[label] == "allow", label


ASKED_ROWS = [r for r in MEASURED_HOME if r[0].startswith(("E ", "N ", "S6 "))]


@pytest.mark.parametrize("row", ASKED_ROWS, ids=[r[0] for r in ASKED_ROWS])
def test_each_harness_home_ask_prompts(row):
    """A Write to a path of each anchored ask entry, from the clone and from HOME, prompts; where the rig's harness
    dir holds the file already the Write tool's read-first check answers first (n/a), and the CLI refuses its own
    session-env, shell-snapshots and .credentials.json outright (refused)."""
    label, _cwd, _tool, _arg, _base, _first, now = row
    assert now in ("ask", "n/a", "refused"), label


def test_residuals_stay_writable_and_memory_is_untouched():
    now = {r[0]: (r[4], r[6]) for r in MEASURED_HOME}
    for label in ("K alt residual docs/x.md", "K alt residual scripts/x.sh", "K alt residual requirements.txt",
                  "K alt residual tests/generated/x.py", "K alt memory md", "K proj default-install memory md",
                  "O alt agent-memory md", "O proj default-install agent-memory md", "O home .review/x.md (base allow)"):
        assert now[label] == ("allow", "allow"), label


def test_every_change_from_base_is_accounted_for():
    """Each decision that differs from base is in exactly one named set, so a new difference fails here."""
    newly_allowed = {r[0] for r in ALL_ROWS if r[4] == "ask" and r[6] == "allow"}
    assert newly_allowed == PROJECT_WRITES | OPEN_REDIRECTS | OPEN_RESIDUAL
    newly_asked = {r[0] for r in ALL_ROWS if r[4] == "allow" and r[6] in ("ask", "n/a")}
    assert newly_asked == ASK_OVERLAP
    newly_denied = {r[0] for r in ALL_ROWS if r[4] != "deny" and r[6] == "deny"}
    assert newly_denied and all("settings.local.json" in label for label in newly_denied)


def test_project_local_settings_entry_is_denied():
    """Nothing else stops a Write of `.claude/settings.local.json` whose keys the harness-switch guard leaves
    alone; measured ask on base and deny now."""
    now = {r[0]: (r[4], r[6]) for r in MEASURED}
    assert now["R Write .claude/settings.local.json"] == ("ask", "deny")
    assert now["R echo > .claude/settings.local.json"] == ("ask", "deny")


# ---- the hook layer -------------------------------------------------------------------------------

def _hook(name: str, tool: str, tool_input: dict, project: Path, home: Path) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
               "cwd": str(project), "session_id": "ob-l08", "transcript_path": str(project / "t.jsonl")}
    env = dict(os.environ, HOME=str(home), CLAUDE_PROJECT_DIR=str(project))
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=60)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    (p / ".claude").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    return p


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": "src/newmodule.py", "content": "x = 1\n"}),
    ("Bash", {"command": "echo hi > notes.md"}),
    ("Bash", {"command": "cat > notes.md <<'EOF'\nhi\nEOF"}),
])
def test_hooks_pass_project_writes(project, tool, tool_input):
    if tool == "Write":
        tool_input = dict(tool_input, file_path=str(project / tool_input["file_path"]))
    for name in ("pretool-claude-config-guard.py", "pretool-harness-switch-guard.py"):
        proc = _hook(name, tool, tool_input, project, project.parent / "home")
        assert proc.returncode == 0, (name, proc.stderr)



def test_config_guard_stops_a_hooks_redirect(project):
    proc = _hook("pretool-claude-config-guard.py", "Bash", {"command": "echo x > .claude/hooks/x.sh"},
                 project, project.parent / "home")
    assert proc.returncode == 2 and "BLOCKED: claude config guard" in proc.stderr


def test_config_guard_stops_a_commands_write(project):
    proc = _hook("pretool-claude-config-guard.py", "Write",
                 {"file_path": str(project / ".claude/commands/x.md"), "content": "x"},
                 project, project.parent / "home")
    assert proc.returncode == 2 and "BLOCKED: claude config guard" in proc.stderr


def test_switch_guard_stops_a_local_settings_permissions_write(project):
    proc = _hook("pretool-harness-switch-guard.py", "Write",
                 {"file_path": str(project / ".claude/settings.local.json"),
                  "content": '{"permissions": {"allow": ["Bash"]}}'},
                 project, project.parent / "home")
    assert proc.returncode == 2 and "BLOCKED: harness-switch" in proc.stderr


def test_switch_guard_leaves_a_benign_local_settings_write_to_the_deny(project):
    """Why the deny entry is needed: the guard passes a settings.local.json write of keys it does not own."""
    proc = _hook("pretool-harness-switch-guard.py", "Write",
                 {"file_path": str(project / ".claude/settings.local.json"), "content": '{"model": "x"}'},
                 project, project.parent / "home")
    assert proc.returncode == 0, proc.stderr
    assert {r[0]: r[6] for r in MEASURED}["R Write .claude/settings.local.json"] == "deny"
