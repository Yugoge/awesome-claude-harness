"""OB-L08: project writes are allowed by `Edit(./**)`; harness-control and home dot-state writes ask again.

Root cause: permissions.allow's Edit entries covered only manifests, .claude/agents|commands, .review,
docs, scripts and tests/generated, so every other write inside the project (Write `src/newmodule.py`,
`echo hi > notes.md`, a heredoc written to a project file) asked in default mode, and was refused
outright headless or overnight. The owner chose `Edit(./**)` (not defaultMode acceptEdits).

`./**` anchors at the session's current directory, so with the current directory at a harness clone
installed through CLAUDE_CONFIG_DIR (docs/installation.md, "Other install locations") or at the home
directory it also allowed writes to the harness's hooks, policies, settings and instruction files and
to the account's dot-state (~/.ssh, ~/.netrc, ~/.config/..., ~/.local/bin), which asked before. The
ask entries put the Write/Edit route to those back to a prompt:

* anchored at the settings source (a single leading slash: the harness home in both install layouts,
  code.claude.com/docs/en/permissions.md "`/path` | Path relative to the settings source"):
  `/CLAUDE.md`, `/agents/**`, `/commands/**`, `/hooks/**`, `/policies/**`, `/schemas/**`,
  `/settings*.json`, `/skills/**` -- what the CLI or a hook loads to decide;
* anchored at the home directory: `~/.*` and `~/.*/**` -- dot files and dot directories directly in it.

"Rules are evaluated in order: deny, then ask, then allow" (permissions.md), so an ask outranks the
allow and never a deny; every deny of the base settings is measured still denying below.

MEASURED holds the decisions of Claude Code 2.1.326's own permission check, run headless offline
(`claude -p --permission-mode default` against a local mock of the Messages API that answers with the
one tool call; a throwaway HOME laid out as a harness home, the settings file holding only the
`permissions` block under test; no hook registered). Columns: label, current directory (proj = a git
project under HOME, home = HOME, harness = ~/.claude, alt = a clone used as CLAUDE_CONFIG_DIR,
althome = HOME with that clone as CLAUDE_CONFIG_DIR, repo = a plain clone under HOME), tool, argument,
then the decision with the base settings (origin/claude/train-c @ d1abc798), with the first OB-L08
commit (c1f2e447, `Edit(./**)` only) and with this settings.json. allow = the write happened, ask =
"Claude requested permissions ..." / "Output redirection ... ", deny = "denied by your permission
settings", n/a = the Write tool refused an existing file not read first (no permission decision seen).

Two measured limits are recorded as OPEN, not hidden:

* ask rules do not reach a Bash output redirect. permissions.md, Redirections: "for `> file`, `>> file`,
  or `2> file`, the check covers your `Edit` allow and deny rules, protected paths, and the working
  directories" -- ask is not in that list, and measured so: `echo X >> hooks/x.py` in the clone and
  `echo X >> .ssh/authorized_keys` in HOME are allowed by `Edit(./**)` whatever ask holds. A Bash ask
  rule cannot match either: the rule is matched against the command with its redirect taken off
  (measured: `Bash(*>*hooks/*)` and twelve similar ask entries left those redirects allowed). Only a
  deny entry, a narrower allow, or a hook can return those to a refusal or a prompt (owner decision).
* `/scripts/**` is not asked: base allowed `scripts/**` with the current directory at the clone, and
  an ask there would newly prompt it. So `harness/scripts/x.sh` from HOME (alt install), which base
  asked, stays allowed; so does a new top-level file in the clone (`new.md`).

Bracket expressions are no way out: `Edit(./[!.]*)`, `Edit(./[^.]*)` and `Edit(./[a-zA-Z0-9_]*)` were
measured matching dot entries and not matching `src/...` (undocumented, unusable).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"

ASK = [
    "Edit(/CLAUDE.md)", "Edit(/agents/**)", "Edit(/commands/**)", "Edit(/hooks/**)", "Edit(/policies/**)",
    "Edit(/schemas/**)", "Edit(/settings*.json)", "Edit(/skills/**)", "Edit(~/.*)", "Edit(~/.*/**)",
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
    ('HM Write .review/x.md (cwd=home, base allow)', 'home', 'Write', '.review/x.md', 'allow', 'allow', 'ask'),
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
    ('HM echo >> ~/.ssh/config (tilde)', 'home', 'Bash', 'echo X >> ~/.ssh/config', 'other', 'other', 'other'),
    ('HM echo >> $HOME/.netrc', 'home', 'Bash', 'echo X >> $HOME/.netrc', 'other', 'other', 'other'),
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

# Base asked, now allowed, by intent: project writes (the lane's purpose), in a project, a plain clone
# under HOME, or HOME itself for a non-dot path.
PROJECT_WRITES = {
    "P1 Write src/newmodule.py", "P2 echo hi > notes.md", "P3 heredoc > project file", "P4 Write top-level README2.md",
    "C Write hooks/x.py", "C echo >> hooks/x.py", "C echo >> settings.json", "C echo >> CLAUDE.md",
    "P sed -i src file (control)", "HM Write proj/.github/x.yml (cwd=home)", "HM Write notes.md (cwd=home)",
    "P Write .github/workflows/x.yml", "P Write hooks/x.py (project dir)", "P Write CLAUDE.md (project)",
    "P Write settings.json (project root)", "P echo > src/.gitignore", "P echo > ./notes.md", "P echo 2>&1 out",
    "HM echo >> proj/.github/x.yml",
}
# Base asked, now allowed, OPEN: Bash output redirects, which ask rules do not reach (module docstring).
OPEN_REDIRECTS = {
    "M echo >> .ssh/authorized_keys", "HM echo >> .ssh/authorized_keys", "M echo >> .config/claude/protected-runtime.json",
    "HM echo >> .config/systemd/user/x.service", "HM echo >> .local/bin/git",
    "A echo >> hooks/x.py", "A echo >> CLAUDE.md", "A echo >> settings.local.json", "A echo >> hooks/pretool-launch.py",
    "A echo >> policies/x.json", "A echo >> agents/x.md", "A echo >> settings.machine.json", "A echo > new.md",
    "AH echo >> harness/CLAUDE.md", "AH echo >> harness/hooks/pretool-launch.py",
}
# Base asked, now allowed, OPEN: not asked so as not to prompt what base allowed (module docstring).
OPEN_NOT_ASKED = {"A Write new.md", "AH Write harness/scripts/x.sh"}
# Base allowed, now asks: `~/.*/**` also covers base-allowed `.review/**` and manifests under a home
# dot directory when the current directory is HOME.
ASK_OVERLAP = {"HM Write .review/x.md (cwd=home, base allow)", "HM Write .config/x/package.json (cwd=home, base allow)"}


def _permissions() -> dict:
    with open(ROOT / "settings.json", encoding="utf-8") as fh:
        return json.load(fh)["permissions"]


def test_the_entries_measured_are_the_entries_shipped():
    perms = _permissions()
    assert perms["ask"] == ASK
    assert "Edit(./**)" in perms["allow"]
    assert "Edit(.claude/settings.local.json)" in perms["deny"]


@pytest.mark.parametrize("row", MEASURED, ids=[r[0] for r in MEASURED])
def test_no_base_deny_is_downgraded(row):
    label, _cwd, _tool, _arg, base, _first, now = row
    if base == "deny":
        assert now == "deny", label


def test_project_writes_run():
    now = {r[0]: r[6] for r in MEASURED}
    for label in ("P1 Write src/newmodule.py", "P2 echo hi > notes.md", "P3 heredoc > project file"):
        assert now[label] == "allow", label


def test_harness_control_and_home_dot_writes_ask_again():
    """Every Write the first commit newly allowed into the harness home or HOME's dot-state asks again."""
    asked = [r for r in MEASURED if r[2] == "Write" and r[4] == "ask" and r[5] == "allow" and r[6] == "ask"]
    labels = {r[0] for r in asked}
    for must in ("A Write hooks/x.py", "A Write policies/x.json", "AH Write harness/hooks/x.py",
                 "A Write settings.local.json", "A Write agents/x.md", "M Write .ssh/config", "M Write .netrc",
                 "M Write .local/bin/git", "M Write .config/systemd/user/x.service", "M Write .docker/config.json",
                 "M Write .kube/config", "M Write .gnupg/gpg.conf", "M Write .pypirc", "HM Write .ssh/authorized_keys"):
        assert must in labels, must


def test_every_change_from_base_is_accounted_for():
    """Each decision that differs from base is in exactly one named set, so a new difference fails here."""
    newly_allowed = {r[0] for r in MEASURED if r[4] == "ask" and r[6] == "allow"}
    assert newly_allowed == PROJECT_WRITES | OPEN_REDIRECTS | OPEN_NOT_ASKED
    newly_asked = {r[0] for r in MEASURED if r[4] == "allow" and r[6] == "ask"}
    assert newly_asked == ASK_OVERLAP
    newly_denied = {r[0] for r in MEASURED if r[4] != "deny" and r[6] == "deny"}
    assert all("settings.local.json" in label for label in newly_denied) and newly_denied
    assert {r[0] for r in MEASURED if r[4] == "allow" and r[6] != "allow"} == ASK_OVERLAP


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
