# venv-repair — restoring `~/.claude/venv` when interpreter symlinks break

`scripts/repair-venv.sh` durably restores the Python interpreter symlinks inside
`~/.claude/venv` so that `python -m pytest` works for every subagent. It is
idempotent — a no-op when the venv is already healthy.

## When to run it

Run `bash scripts/repair-venv.sh` whenever any of these symptoms appear:

- `file ~/.claude/venv/bin/python` reports `broken symbolic link to python3`
- `~/.claude/venv/bin/python --version` exits 127 with `No such file or directory`
- A subagent that activates the venv falls back to grep-only verification (because
  pytest cannot be invoked)
- `find ~/.claude/venv/bin -maxdepth 1 -name 'python*' -type l -xtype l` returns
  any path (broken-symlink finder; empty output is the healthy state)

## What it does

1. Resolves the venv path from the script's own location (`$BASH_SOURCE/../venv`);
   override with `--venv <path>` if you keep the venv elsewhere.
2. Parses `<venv>/pyvenv.cfg` for the `executable = <path>` line — never hardcodes
   `/usr/bin/python3.12`, so it survives Python minor-version bumps.
3. Verifies the parsed executable exists and is executable.
4. Creates `<venv>/bin/python3 -> <executable>` only if missing or broken; never
   overwrites a healthy entry.
5. Verifies success by running `python -m pytest --version`, `python3 -m pytest
   --version`, `python3.12 -m pytest --version` and asserting all three exit 0
   with output matching `^pytest\s+\d+\.\d+`.
6. Confirms `<venv>/bin/python -c 'import sys; assert sys.prefix.endswith("venv")'`
   exits 0 — proves the resolved interpreter genuinely lives in the venv (not a
   system-wide Python with global pytest leaking in).

## What it deliberately does NOT do

- Does not reinstall, upgrade, or downgrade any site-package (pytest version is
  not touched).
- Does not recreate the venv as a whole.
- Does not modify any subagent or hook code that consumes `venv/bin/activate`.

## Why this matters

A broken venv interpreter symlink is the operational driver of "harness lies"
patterns: when subagents fail to invoke pytest they silently fall back to grep,
which can produce vacuous green reports (see `agents/qa.md` Phase 5 step 6 — the
vacuity invariant — and `scripts/qa-manifest-guard.py` — the canonical guard
script that QA invokes before emitting `manifest_verification`).

Running `repair-venv.sh` is one of the cheapest interventions in the codebase
and should be the first reflex when any subagent reports a pytest invocation
failure.
