"""R7b: the private-literal rule of scripts/check-public-core.sh and the fail-closed
pre-commit hook hooks/git-hooks/pre-commit.

Every case runs in a throwaway git repository assembled from copies of the scripts it
needs, with HOME, CLAUDE_CONFIG_DIR and XDG_CONFIG_HOME pointed at temporary directories,
system git config disabled and every inherited GIT_* variable dropped, so neither the
real checkout nor any real home configuration is read or written. The only literal ever
listed is the synthetic account-style stand-in LITERAL.

The temporary tree is a minimal harness every OTHER checkout check of check-public-core.sh
passes on (a ledger classifying each top-level path, the harness's own residue-allowlist
entries for the copied scripts, since the generic residue rule scans every tracked file),
so an exit status observed in checkout mode is attributable to the private-literal rule alone.

Scopes under test: the default run reads every tracked file's INDEX content;
--private-literals reads only the lines and path names the staged change adds relative to
HEAD (everything when there is no HEAD); --scan-root reads every file under the archive.
The list is private-literals.txt in the MAIN working tree, also for linked worktrees.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECKER = "scripts/check-public-core.sh"
HOOK = "hooks/git-hooks/pre-commit"
RENDER = "scripts/install/render-settings"
PRE_COMMIT_CHECK = "hooks/pre-commit-check.sh"
SENTINEL_LINT = "hooks/sentinel-lint.sh"
COPIED = (CHECKER, HOOK, PRE_COMMIT_CHECK, SENTINEL_LINT, "hooks/lib/claude_home.sh",
          "scripts/lib/release_membership.py")
LIST = "private-literals.txt"
# Split so this source never carries the listed literal whole.
LITERAL = "acct-test-" + "123"
BOOTSTRAP_MARKER = "# claude-harness pre-commit (installed by scripts/bootstrap)"
SKIP_PREFIX = "SKIP: private-literal rule"
STAGED_PASS = "PASS: no listed private literal (scope: staged)"
REDACTED = f"<path with {LIST} line 1>"

LEDGER = """# Minimal boundary ledger for the private-literal tests

<!-- BEGIN:public-core-manifest -->
| Path | Class | Rationale |
|---|---|---|
| `PUBLIC-CORE.md` | `shared/infra` | this ledger |
| `docs/` | `public-core` | prose under test |
| `hooks/` | `shared/infra` | copied hook scripts |
| `policies/` | `shared/infra` | residue allowlist |
| `scripts/` | `shared/infra` | copied gate scripts |
<!-- END:public-core-manifest -->
"""
ALLOWLIST = "policies/public-core-residue-allowlist.v1.json"


def _copied_allowlist() -> str:
    """The harness allowlist narrowed to the copied scripts (same bytes, same keys)."""
    doc = json.loads((REPO / ALLOWLIST).read_text(encoding="utf8"))
    verbatim = COPIED if USING_RENDER_SETTINGS_STUB else (*COPIED, RENDER)
    doc["entries"] = [e for e in doc["entries"] if e["path"] in verbatim]
    return json.dumps(doc, indent=2) + "\n"

STUB_RENDER_PASS = (
    "#!/usr/bin/env python3\n"
    '"""Test stand-in for scripts/install/render-settings: accepts `check --staged` only."""\n'
    "import sys\n"
    'sys.exit(0 if sys.argv[1:] == ["check", "--staged"] else 2)\n'
)
STUB_RENDER_FAIL = (
    "#!/usr/bin/env python3\n"
    '"""Test stand-in for scripts/install/render-settings whose staged check fails."""\n'
    "import sys\n"
    'print("settings.json is staged in machine form (test stub)", file=sys.stderr)\n'
    "sys.exit(1)\n"
)


def _render_settings_has_staged_check() -> bool:
    src = REPO / RENDER
    return src.is_file() and re.search(r"""["']--staged["']""", src.read_text(encoding="utf8")) is not None


USING_RENDER_SETTINGS_STUB = not _render_settings_has_staged_check()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def _script(path: Path, text: str) -> None:
    _write(path, text)
    path.chmod(0o755)


def _git(root: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True, check=True)


def _check(root: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(root / CHECKER), *args], cwd=root, env=env,
                          capture_output=True, text=True)


def _lines(out: str, prefix: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(prefix)]


def _hits(r: subprocess.CompletedProcess) -> list[str]:
    return _lines(r.stdout, "FAIL: private literal ")


def _head(root: Path, env: dict) -> str:
    return _git(root, env, "rev-parse", "HEAD").stdout.strip()


def _commit(root: Path, env: dict, *paths: str, verify: bool = True) -> subprocess.CompletedProcess:
    _git(root, env, "add", "--", *paths)
    return subprocess.run(["git", "commit", "-q", "-m", "test change", *(() if verify else ("--no-verify",))],
                          cwd=root, env=env, capture_output=True, text=True)


def _never_printed(r: subprocess.CompletedProcess) -> None:
    assert LITERAL not in r.stdout + r.stderr, "a listed literal was printed"


@pytest.fixture
def env(tmp_path: Path) -> dict:
    dirs = {name: tmp_path / name for name in ("home", "claude-config", "xdg-config")}
    for d in dirs.values():
        d.mkdir()
    dropped = {"CLAUDE_HOME", "CLAUDE_PROJECT_DIR", "SENTINEL_LINT_ROOT", "SENTINEL_LINT_VERBOSE"}
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in dropped}
    e.update(HOME=str(dirs["home"]), CLAUDE_CONFIG_DIR=str(dirs["claude-config"]),
             XDG_CONFIG_HOME=str(dirs["xdg-config"]), GIT_CONFIG_NOSYSTEM="1",
             GIT_AUTO_STAGE_ALL="0", GIT_BLOCK_ON_UNTRACKED="0", GIT_WARN_UNTRACKED="1")
    return e


@pytest.fixture
def repo(tmp_path: Path, env: dict) -> Path:
    """A committed minimal harness tree; the private-literal list stays untracked."""
    root = tmp_path / "harness"
    for rel in COPIED:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    if USING_RENDER_SETTINGS_STUB:
        _script(root / RENDER, STUB_RENDER_PASS)
    else:
        (root / RENDER).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / RENDER, root / RENDER)
    _write(root / "PUBLIC-CORE.md", LEDGER)
    _write(root / ALLOWLIST, _copied_allowlist())
    _write(root / "docs/notes.md", "# Notes\n\nNothing private here.\n")
    _git(root, env, "init", "-q")
    _git(root, env, "config", "user.name", "sandbox")
    _git(root, env, "config", "user.email", "sandbox@example.invalid")
    _write(root / ".git/info/exclude", f"/{LIST}\n")
    _git(root, env, "add", "-A")
    _git(root, env, "commit", "-q", "-m", "base")
    return root


@pytest.fixture
def hooked(repo: Path, env: dict) -> Path:
    """The repo with the tracked hook installed where git looks for it."""
    hooks = Path(_git(repo, env, "rev-parse", "--git-path", "hooks").stdout.strip())
    hooks = hooks if hooks.is_absolute() else repo / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / HOOK, hooks / "pre-commit")
    (hooks / "pre-commit").chmod(0o755)
    return repo


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

def test_no_list_prints_skip_and_leaves_the_exit_status_to_the_other_checks(repo, env):
    assert not (repo / LIST).exists()
    clean = _check(repo, env)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    skip = _lines(clean.stdout, SKIP_PREFIX)
    assert len(skip) == 1 and skip[0].endswith(f"/{LIST})")
    assert not _lines(clean.stdout, "FAIL")
    # An unrelated failing check still decides the exit status on its own.
    _write(repo / "stray.txt", "an unclassified top-level path\n")
    _git(repo, env, "add", "stray.txt")
    dirty = _check(repo, env)
    assert dirty.returncode == 1
    assert len(_lines(dirty.stdout, SKIP_PREFIX)) == 1
    assert _lines(dirty.stdout, "FAIL: unclassified top-level tracked path")
    only = _check(repo, env, "--private-literals")
    assert only.returncode == 0, only.stdout + only.stderr
    assert only.stdout.splitlines() == skip, "nothing but the SKIP line"


@pytest.mark.parametrize("content", ["", "# a comment\n\n   \n\t# an indented comment\r\n  \r\n"],
                         ids=["zero-bytes", "comments-and-blank-lines"])
def test_list_holding_no_literal_is_skipped(repo, env, content):
    _write(repo / LIST, content)
    for args in ((), ("--private-literals",)):
        r = _check(repo, env, *args)
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(_lines(r.stdout, SKIP_PREFIX)) == 1
        assert not _lines(r.stdout, "PASS: no listed private literal"), "nothing may be scanned"


def test_unreadable_list_fails_closed(repo, env):
    (repo / LIST).mkdir()
    r = _check(repo, env, "--private-literals")
    assert r.returncode == 1
    assert _lines(r.stdout, f"FAIL: private-literal rule: cannot read {LIST}")
    assert not _lines(r.stdout, SKIP_PREFIX)


def test_linked_worktree_uses_the_main_tree_list(repo, env, tmp_path):
    wt = tmp_path / "linked"
    _git(repo, env, "worktree", "add", "-q", "--detach", str(wt))
    _write(repo / LIST, f"{LITERAL}\n")
    _write(wt / "docs/leak.md", f"{LITERAL}\n")
    _git(wt, env, "add", "docs/leak.md")
    r = _check(wt, env, "--private-literals")
    assert r.returncode == 1, r.stdout + r.stderr
    assert _hits(r) == [f"FAIL: private literal ({LIST} line 1) -> docs/leak.md:1"]
    _never_printed(r)
    # A list in the linked worktree itself is not consulted.
    (repo / LIST).rename(wt / LIST)
    moved = _check(wt, env, "--private-literals")
    assert moved.returncode == 0 and len(_lines(moved.stdout, SKIP_PREFIX)) == 1, moved.stdout


# ---------------------------------------------------------------------------
# Default scope: the index content of every tracked file
# ---------------------------------------------------------------------------

def test_listed_literal_in_a_tracked_file_fails_naming_file_and_list_line_only(repo, env):
    # CRLF line ends and padding are trimmed; the literal is on list line 3.
    _write(repo / LIST, f"# private values of this machine\r\n\r\n   {LITERAL}  \r\n")
    _write(repo / "docs/notes.md",
           f"# Notes\nowner account {LITERAL} here\nupper case {LITERAL.upper()} is another string\n")
    assert _commit(repo, env, "docs/notes.md").returncode == 0
    r = _check(repo, env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert _hits(r) == [f"FAIL: private literal ({LIST} line 3) -> docs/notes.md:2"], \
        "one hit, file:line and list line; matching is case-sensitive"
    _never_printed(r)
    # Committed before: not part of what the next staged change adds.
    staged = _check(repo, env, "--private-literals")
    assert staged.returncode == 0 and staged.stdout.splitlines() == [STAGED_PASS], staged.stdout


def test_staged_literal_is_refused_after_the_working_tree_dropped_it(repo, env):
    _write(repo / LIST, f"{LITERAL}\n")
    _write(repo / "docs/secret.md", f"{LITERAL}\n")
    _git(repo, env, "add", "docs/secret.md")
    _write(repo / "docs/secret.md", "scrubbed in the working tree only\n")   # not re-staged
    for args in ((), ("--private-literals",)):
        r = _check(repo, env, *args)
        assert r.returncode == 1, r.stdout + r.stderr
        assert _hits(r) == [f"FAIL: private literal ({LIST} line 1) -> docs/secret.md:1"]
        _never_printed(r)


def test_unstaged_working_tree_content_is_not_scanned(repo, env):
    _write(repo / LIST, f"{LITERAL}\n")
    _write(repo / "docs/notes.md", f"unstaged {LITERAL}\n")
    for args in ((), ("--private-literals",)):
        r = _check(repo, env, *args)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _hits(r)


def test_default_scope_reads_committed_settings_not_the_working_copy(repo, env):
    """settings.json is smudged into machine form in the working tree; the clean form is
    what is committed, so a machine value present only in the working copy is no hit."""
    _write(repo / "settings.json", '{"env": {"OWNER": "acct-a"}}\n')
    _git(repo, env, "add", "settings.json")
    _write(repo / "settings.json", f'{{"env": {{"OWNER": "{LITERAL}"}}}}\n')   # smudged copy
    _write(repo / LIST, f"{LITERAL}\n")
    r = _check(repo, env)
    assert not _hits(r), r.stdout


# ---------------------------------------------------------------------------
# --private-literals: what the staged change adds
# ---------------------------------------------------------------------------

def test_private_literals_refuses_staged_additions(repo, env):
    _write(repo / LIST, f"{LITERAL}\n")
    _write(repo / "docs/notes.md", f"# Notes\n\nNothing private here.\nadded {LITERAL}\n")
    _write(repo / "docs/new.md", f"first\n{LITERAL} on line two\n")
    _git(repo, env, "add", "docs")
    r = _check(repo, env, "--private-literals")
    assert r.returncode == 1, r.stdout + r.stderr
    assert sorted(_hits(r)) == [f"FAIL: private literal ({LIST} line 1) -> docs/new.md:2",
                                f"FAIL: private literal ({LIST} line 1) -> docs/notes.md:4"]
    _never_printed(r)


def test_private_literals_ignores_pre_existing_occurrences(repo, env):
    _write(repo / "docs/old.md", f"legacy {LITERAL}\n")
    _write(repo / "docs/touched.md", f"kept {LITERAL}\nsecond line\n")
    assert _commit(repo, env, "docs").returncode == 0
    _write(repo / LIST, f"{LITERAL}\n")
    # Touch the file around the old line, and another file; leave docs/old.md alone.
    _write(repo / "docs/touched.md", f"kept {LITERAL}\nsecond line, edited\nthird line\n")
    _write(repo / "docs/notes.md", "# Notes\n\nStill nothing private.\n")
    _git(repo, env, "add", "docs")
    r = _check(repo, env, "--private-literals")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines() == [STAGED_PASS]
    full = _check(repo, env)
    assert sorted(_hits(full)) == [f"FAIL: private literal ({LIST} line 1) -> docs/old.md:1",
                                   f"FAIL: private literal ({LIST} line 1) -> docs/touched.md:1"], \
        "the default scope still reports every occurrence"


def test_private_literals_refuses_a_staged_path_name_and_redacts_it(repo, env):
    _write(repo / LIST, f"{LITERAL}\n")
    _write(repo / "docs" / f"{LITERAL}.md", "clean content\n")
    _write(repo / "docs" / f"empty-{LITERAL}", "")
    _git(repo, env, "add", "docs")
    r = _check(repo, env, "--private-literals")
    assert r.returncode == 1
    assert _hits(r) == [f"FAIL: private literal ({LIST} line 1) -> {REDACTED} (path name)"] * 2
    _never_printed(r)


def test_private_literals_without_head_checks_every_staged_line(repo, env):
    _write(repo / "docs/old.md", f"{LITERAL}\n")
    assert _commit(repo, env, "docs/old.md").returncode == 0
    _write(repo / LIST, f"{LITERAL}\n")
    assert _check(repo, env, "--private-literals").returncode == 0
    _git(repo, env, "update-ref", "-d", "HEAD")   # unborn branch, index kept
    r = _check(repo, env, "--private-literals")
    assert r.returncode == 1
    assert _hits(r) == [f"FAIL: private literal ({LIST} line 1) -> docs/old.md:1"]


def test_private_literals_mode_runs_only_the_rule(repo, env):
    _write(repo / LIST, f"{LITERAL}\n")
    _git(repo, env, "rm", "-q", "PUBLIC-CORE.md")   # the ledger checks now fail outright
    assert _check(repo, env).returncode == 1
    r = _check(repo, env, "--private-literals")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines() == [STAGED_PASS]


# ---------------------------------------------------------------------------
# --scan-root: every file under the archive
# ---------------------------------------------------------------------------

def test_archive_mode_scans_every_file_under_the_root(repo, env, tmp_path):
    stage = tmp_path / "stage"
    _write(stage / "release-membership.v1.json", json.dumps({"include": ["*"]}) + "\n")
    _write(stage / "docs/guide.md", f"intro\n{LITERAL} shipped\n")
    _write(stage / "docs" / f"{LITERAL}.txt", "clean\n")
    args = ("--scan-root", str(stage), "--release-manifest", str(stage / "release-membership.v1.json"))
    unlisted = _check(repo, env, *args)
    assert len(_lines(unlisted.stdout, SKIP_PREFIX)) == 1 and not _hits(unlisted), unlisted.stdout
    _write(repo / LIST, f"{LITERAL}\n")
    r = _check(repo, env, *args)
    assert r.returncode == 1
    assert sorted(_hits(r)) == sorted([f"FAIL: private literal ({LIST} line 1) -> docs/guide.md:2",
                                       f"FAIL: private literal ({LIST} line 1) -> {REDACTED} (path name)"])
    _never_printed(r)


# ---------------------------------------------------------------------------
# The pre-commit hook
# ---------------------------------------------------------------------------

def test_hook_carries_the_bootstrap_marker_and_no_bypass_advice():
    src = (REPO / HOOK).read_text(encoding="utf8")
    assert BOOTSTRAP_MARKER in src.splitlines()
    assert "--no-verify" not in src


@pytest.mark.parametrize("listed", [True, False], ids=["with-list", "without-list"])
def test_hook_allows_a_clean_commit(hooked, env, listed):
    if listed:
        _write(hooked / LIST, f"{LITERAL}\n")
    before = _head(hooked, env)
    _write(hooked / "docs/clean.md", "nothing private\n")
    r = _commit(hooked, env, "docs/clean.md")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _head(hooked, env) != before


def test_hook_refuses_a_commit_adding_a_listed_literal(hooked, env):
    _write(hooked / LIST, f"{LITERAL}\n")
    before = _head(hooked, env)
    _write(hooked / "docs/leak.md", f"account {LITERAL}\n")
    r = _commit(hooked, env, "docs/leak.md")
    assert r.returncode != 0
    assert "commit REFUSED by the private-literal check" in r.stderr
    assert "docs/leak.md:1" in r.stdout + r.stderr
    _never_printed(r)
    assert _head(hooked, env) == before


def test_hook_does_not_block_an_unrelated_commit_over_a_pre_existing_literal(hooked, env):
    _write(hooked / "docs/legacy.md", f"legacy {LITERAL}\n")
    assert _commit(hooked, env, "docs/legacy.md", verify=False).returncode == 0
    _write(hooked / LIST, f"{LITERAL}\n")
    before = _head(hooked, env)
    _write(hooked / "docs/clean.md", "nothing private\n")
    r = _commit(hooked, env, "docs/clean.md")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _head(hooked, env) != before


def _assert_refused(hooked: Path, env: dict, needle: str, *paths: str) -> None:
    before = _head(hooked, env)
    if not paths:
        _write(hooked / "docs/clean.md", "nothing private\n")
        paths = ("docs/clean.md",)
    r = _commit(hooked, env, *paths)
    assert r.returncode != 0, f"commit was allowed; expected a refusal naming: {needle}"
    assert f"commit REFUSED by the {needle}" in r.stderr, r.stderr
    assert _head(hooked, env) == before


def test_hook_refuses_when_check_public_core_is_renamed_away(hooked, env):
    (hooked / CHECKER).rename(hooked / f"{CHECKER}.off")
    _assert_refused(hooked, env, "private-literal check: scripts/check-public-core.sh is missing")


def test_hook_refuses_when_render_settings_is_missing(hooked, env):
    (hooked / RENDER).unlink()
    _assert_refused(hooked, env, "settings check: scripts/install/render-settings is missing")


def test_hook_refuses_when_the_staged_settings_check_fails(hooked, env):
    _script(hooked / RENDER, STUB_RENDER_FAIL)
    _assert_refused(hooked, env, "settings check: scripts/install/render-settings check --staged failed")


def test_hook_refuses_when_pre_commit_check_is_missing(hooked, env):
    (hooked / PRE_COMMIT_CHECK).unlink()
    _assert_refused(hooked, env, "untracked-file check: hooks/pre-commit-check.sh is missing")


def test_hook_refuses_when_sentinel_lint_is_needed_but_missing(hooked, env):
    (hooked / SENTINEL_LINT).unlink()
    _write(hooked / "docs/clean.md", "nothing private\n")
    assert _commit(hooked, env, "docs/clean.md").returncode == 0, "not needed: no orchestrator file staged"
    _write(hooked / "commands/dev.md", "# dev\n")
    _assert_refused(hooked, env, "sentinel lint: hooks/sentinel-lint.sh is missing", "commands/dev.md")


def test_hook_refuses_when_sentinel_lint_fails(hooked, env):
    _write(hooked / "commands/dev.md", "# dev, without the registry anchor\n")
    _assert_refused(hooked, env, "sentinel lint: hooks/sentinel-lint.sh failed", "commands/dev.md")


def test_hook_chains_to_pre_commit_local(hooked, env, tmp_path):
    hooks = Path(_git(hooked, env, "rev-parse", "--git-path", "hooks").stdout.strip())
    hooks = hooks if hooks.is_absolute() else hooked / hooks
    trace = tmp_path / "pre-commit-local.trace"
    _script(hooks / "pre-commit.local", f'#!/bin/sh\necho "args=$#" > "{trace}"\nexit 7\n')
    before = _head(hooked, env)
    _write(hooked / "docs/clean.md", "nothing private\n")
    assert _commit(hooked, env, "docs/clean.md").returncode != 0, "the chained hook's refusal was ignored"
    assert trace.read_text(encoding="utf8") == "args=0\n"
    assert _head(hooked, env) == before
    _script(hooks / "pre-commit.local", "#!/bin/sh\nexit 0\n")
    assert _commit(hooked, env, "docs/clean.md").returncode == 0
    assert _head(hooked, env) != before
