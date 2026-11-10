# Quick Start — the hooks layer

> **Important — this harness does NOT commit after each response, and pushes nothing unless
> `GIT_AUTO_PUSH` is exactly `1`.** An earlier version of this guide described a "commit + push
> after every response" model. That model is **wrong for this repo**. Automated snapshots go to
> `refs/checkpoints/<branch>` and never move HEAD. An agent's commit and push pass through
> single-use grants: `/commit` writes the commit grant that `hooks/pretool-git-privilege-guard.py`
> checks, and `/push`'s push-analyst writes the push grant that `scripts/execute-push.py` validates
> and spends before `hooks/push.sh` pushes. Only with `GIT_AUTO_PUSH=1` (the shipped
> `settings.json` sets `0`) do the automatic pushes run: the checkpoint ref, the installed
> post-commit hooks, the fswatch watcher's branch and a new repository's initial commit. For the
> real model see the root [`README.md`](../README.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md) §6.

---

## 📋 Required Steps

### 1️⃣ Restart Claude Code

Configuration has been updated, restart Claude Code to take effect:

```bash
# Exit current session and restart Claude Code
exit
```

### 2️⃣ Install GitHub CLI (Optional, but Highly Recommended)

**macOS:**
```bash
brew install gh
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt install gh
```

**Other Systems:**
Visit https://cli.github.com/

### 3️⃣ Login to GitHub

```bash
gh auth login
```

Follow the prompts to select:
- GitHub.com
- HTTPS
- Login with a web browser

### 4️⃣ Configure Auto-Create Repository (Optional)

Edit your shell configuration file:

```bash
# For Bash users
nano ~/.bashrc

# For Zsh users
nano ~/.zshrc
```

Add the following:

```bash
# Claude Code auto-create GitHub repository (hooks/session-git-init.sh runs only
# when CLAUDE_SESSION_GIT_INIT is set; the repository is pushed only with GIT_AUTO_PUSH=1)
export CLAUDE_SESSION_GIT_INIT=1
export CLAUDE_AUTO_CREATE_REPO=true
```

Save and reload:

```bash
source ~/.bashrc  # or source ~/.zshrc
```

---

## 🎯 Test Configuration

### Test 1: Check Script Permissions

```bash
ls -lh ~/.claude/hooks/*.sh
```

Should see `-rwxr-xr-x` (x indicates executable)

### Test 2: Manually Run Scripts

```bash
# Validate settings.json parses
python3 -m json.tool ~/.claude/settings.json >/dev/null && echo "settings.json OK"

# Repository initialization is handled by the wired SessionStart hook
# (~/.claude/hooks/session-git-init.sh); it runs at session start when
# CLAUDE_SESSION_GIT_INIT is set, not by hand.
```

### Test 3: Verify GitHub CLI

```bash
gh auth status
```

Should show logged in.

---

## 🔄 Workflow Examples

### Scenario 1: New Project

```bash
# 1. Create new project directory
mkdir my-new-project
cd my-new-project

# 2. Start Claude Code
claude-code  # or your launch command

# 3. Work proceeds through the grant-gated pipeline:
#    - SessionStart hooks announce the environment
#    - Edits go to a dev subagent; the git kernel gates every mutation
#    - Nothing is committed on HEAD and nothing is pushed automatically (unless
#      GIT_AUTO_PUSH=1) — you run /commit and /push, each under its own single-use grant
```

### Scenario 2: Existing Project

```bash
# 1. Enter existing project
cd existing-project

# 2. Start Claude Code
claude-code

# 3. Same grant-gated model — nothing is committed on HEAD or pushed automatically
#    (unless GIT_AUTO_PUSH=1); /commit and /push each require a single-use grant
```

---

## Custom Options

Automatic push is off unless `GIT_AUTO_PUSH` is exactly `1` (any other value, unset included,
keeps every automatic push off; the shipped `settings.json` sets `0`). Commits and pushes by an
agent are grant-gated: you run `/commit` and `/push` explicitly, each under its own single-use grant. There is no auto-commit script to edit — to
customize commit behavior, configure the release commands in `commands/` and the
grant kernel in `settings.json` instead.

### Project-Level Configuration

Create custom configuration for a specific project:

```bash
cd your-project
mkdir -p .claude
nano .claude/settings.json
```

---

## Verify Configuration

```bash
# settings.json must parse as valid JSON
python3 -m json.tool ~/.claude/settings.json >/dev/null && echo "settings.json OK"

# Inspect the grant-gated git wiring (PreToolUse git guards)
grep -o 'pretool-git-privilege-guard.py' ~/.claude/settings.json | head -1
```

---

## 📚 Next Steps

- Read the full overview + dependency matrix: [`README.md`](../README.md)
- Deep architecture (the grant kernel): [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Visit Claude Code docs: https://docs.claude.com/

---

## FAQ

**Q: Why didn't my work get committed automatically?**

A: By design — nothing commits on HEAD on its own, and nothing pushes unless `GIT_AUTO_PUSH=1`.
You type the command in the Claude Code session: `/commit` commits (it first runs `/close`'s
steps for a task that is not closed yet) and `/push` pushes, each under its own single-use grant.
`/allow git commit` or `/allow git push` grants one matching call instead. These commands are
human-only: the model cannot invoke them.

**Q: A commit or push is being blocked.**

A: That is the git kernel working as designed. `hooks/pretool-git-privilege-guard.py` refuses a
`git commit` or `git push` from the Bash tool, for the main agent and every subagent, unless a
grant covers it: an agent's commit lands through `/commit`, a push through `/push`. `/do` consent
does not cover `git commit`, `git push`, a git operation the guard refuses without `/do` that can
move the protected branch (a merge, hard reset or ref write onto it) or whose landing branch it
cannot tell, or a git command the guard cannot classify; a merge into it lands through `/merge`.
`/allow <command>` grants one matching call (300 s). Refused even with a grant: a force, delete
or ref-rewrite push (`--force`, `-f`, `--force-with-lease`, `--delete`, `--mirror`, a `+` or `:`
refspec; `/allow git push --force` is itself refused by the settings deny), and a commit that skips
the commit hooks (`--no-verify`, `-n`, a `core.hooksPath` override).

**Q: How do I temporarily disable the harness?**

A: Move the settings file aside, then restore it:

```bash
mv ~/.claude/settings.json ~/.claude/settings.json.disabled
mv ~/.claude/settings.json.disabled ~/.claude/settings.json   # restore
```

---

## Complete!

You can now start using Claude Code. To be explicit about the git model:
1. With `CLAUDE_SESSION_GIT_INIT` set, the harness initializes a Git repository (and its
   initial commit) at session start in a directory that has none.
2. It does **NOT** commit after each response — you run `/commit` (grant-gated).
3. It pushes nothing unless `GIT_AUTO_PUSH` is exactly `1` — you run `/push` (grant-gated).
   Instead of `/commit` or `/push`, `/allow git commit` or `/allow git push` grants one call.

See [`README.md`](../README.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md) §6 for the full grant kernel.
