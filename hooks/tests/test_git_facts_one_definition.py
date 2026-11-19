"""Facts about git that several hooks need are stated once, and every hook that reads them agrees.

Each class is one fact. Before these merges each hook carried its own copy, the copies differed,
and two hooks gave different answers about the same git command: the config guard read `HEAD` as
the subcommand of `git --attr-source HEAD diff`, the harness-switch rule read `.` as the
subcommand of `git -C . diff` and refused a plain diff of a settings file, and so on. The inputs
are those on which the copies disagreed.

The in-process checks import the hooks from this tree with a scratch HOME, state directory and
TMPDIR; the hook runs use the same scratch environment and a scratch project.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
for _p in (str(HOOKS), str(HOOKS / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import shell_parse as sp  # noqa: E402
from lib import git_command_classifier as gc  # noqa: E402
from lib.runtime_guard import git_cmds  # noqa: E402


def _load(rel: str):
    path = HOOKS / rel
    name = "defs_git_" + path.stem.replace("-", "_")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    root = tmp_path_factory.mktemp("defs-git")
    home, project, state, tmp = root / "home", root / "proj", root / "state", root / "tmp"
    for d in (home / ".claude", project / ".claude" / "hooks", project / "src", state, tmp):
        d.mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "settings.json").write_text("{}\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "TMPDIR": str(tmp), "CLAUDE_PROJECT_DIR": str(project), "PYTHONDONTWRITEBYTECODE": "1",
           "LANG": "C.UTF-8"}
    return env, project


def run_hook(scratch, hook: str, command: str) -> int:
    env, project = scratch
    payload = {"session_id": "sess-defs-git", "transcript_path": str(project / "none.jsonl"),
               "cwd": str(project), "hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": "Bash", "tool_input": {"command": command}, "tool_use_id": "toolu_defsgit"}
    proc = subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(project), env=env, timeout=60)
    return proc.returncode


# The argument lists on which the subcommand finders disagreed (audit f13): every global option of
# git, each before `diff`.
GLOBAL_OPTION_FORMS = [
    [], ["-C", "."], ["-c", "a=b"], ["--git-dir", ".git"], ["--git-dir=.git"], ["--work-tree", "."],
    ["--namespace", "x"], ["--super-prefix", "x/"], ["--attr-source", "HEAD"], ["--shallow-file", "x"],
    ["--config-env", "a.b=HOME"], ["--exec-path=/usr/lib/git-core"], ["--no-pager"], ["-P"], ["-p"],
    ["--paginate"], ["--bare"], ["--no-replace-objects"], ["--literal-pathspecs"],
    ["--no-optional-locks"], ["--no-lazy-fetch"], ["--no-advice"], ["--icase-pathspecs"],
]


class TestGitCommandParsing:
    """git-command-parsing, git-global-value-options, git-global-flags: which word is the subcommand."""

    @pytest.mark.parametrize("opts", GLOBAL_OPTION_FORMS, ids=lambda o: " ".join(o) or "plain")
    def test_every_finder_reads_diff(self, opts):
        args = opts + ["diff"]
        cg = _load("pretool-claude-config-guard.py")
        hs = _load("pretool-harness-switch-guard.py")
        found = {
            "shared parser": [i.subcommand for i in sp.git_invocations(sp.parse("git " + " ".join(args)))],
            "classifier": [gc._git_subcommand(list(args))[0]],
            "runtime guard": [git_cmds._git_subcommand_index(["git"] + args, 0)[0]],
            "config guard": [cg._git_subcommand(list(args))],
        }
        assert all(v == ["diff"] for v in found.values()), found
        # The harness-switch rule: a diff, whatever global option precedes it, only reads.
        assert hs._read_only(["git"] + args)

    @pytest.mark.parametrize("opts", [["-C", "."], ["--git-dir", ".git"], ["--work-tree", "."],
                                      ["--namespace", "x"], ["--attr-source", "HEAD"],
                                      ["--config-env", "a.b=HOME"]], ids=" ".join)
    def test_harness_switch_rule_passes_a_diff_behind_a_global_option(self, scratch, opts):
        """audit f05 part 2: `git -C . diff -- .claude/settings.json` was refused, `git diff -- ...` not."""
        cmd = "git " + " ".join(opts + ["diff", "--", ".claude/settings.json"])
        assert run_hook(scratch, "pretool-harness-switch-guard.py", cmd) == 0

    def test_harness_switch_rule_keeps_the_value_of_dash_c(self):
        """`-c a=b` is git's option and its value, not a prefix assignment of the shell."""
        hs = _load("pretool-harness-switch-guard.py")
        assert hs._read_only(["git", "-c", "a=b", "diff", "--", ".claude/settings.json"])
        assert hs._read_only(["LC_ALL=C", "git", "diff"])
        assert not hs._read_only(["git", "-c", "a=b", "checkout", "--", ".claude/settings.json"])

    def test_one_table_of_global_options(self):
        """The removal policy, the bulk and disk rules, userintent and the read-only gate read shell_parse's."""
        from lib import bash_execution_boundary as beb, bash_safety_rules as bsr
        ui = _load("pretool-wrapper-userintent.py")
        assert beb.GIT_GLOBAL["bool"] == set(sp.GIT_GLOBAL_FLAGS)
        assert beb.GIT_GLOBAL["val"] == set(sp.GIT_GLOBAL_VALUE_OPTS)
        assert ui._GIT_GLOBAL_VALUE == sp.GIT_GLOBAL_VALUE_OPTS
        assert sp.GIT_INERT_FLAGS <= sp.GIT_GLOBAL_FLAGS and sp.GIT_LOCATION_OPTS <= sp.GIT_GLOBAL_VALUE_OPTS
        assert bsr._SD_GIT_GLOBAL_FLAGS == sp.GIT_INERT_FLAGS | {"-p", "--paginate"}
        assert bsr._DG_GIT_GLOBAL_OK == sp.GIT_INERT_FLAGS | {"--version", "--help"}


# audit f05 part 2: reads of the harness-switch rule's settings file it refused, and the stash it passed.
READS_OF_A_NAMED_FILE = [
    "git annotate {T}", "git whatchanged -- {T}", "git shortlog -- {T}", "git rev-list HEAD -- {T}",
    "git ls-tree HEAD {T}", "git check-ignore {T}", "git diff-tree HEAD -- {T}", "git diff-index HEAD -- {T}",
    "git diff-files -- {T}", "git reflog -- {T}",
]


class TestGitReadSubcommands:
    """git-read-subcommands: which git subcommands only read the files they name."""

    @pytest.mark.parametrize("template", READS_OF_A_NAMED_FILE)
    def test_harness_switch_rule_passes_a_read(self, scratch, template):
        assert run_hook(scratch, "pretool-harness-switch-guard.py", template.format(T=".claude/settings.json")) == 0

    def test_harness_switch_rule_refuses_a_stash_of_the_file(self, scratch):
        """`git stash push -- <file>` saves the file and reverts it: a write."""
        assert run_hook(scratch, "pretool-harness-switch-guard.py", "git stash push -- .claude/settings.json") == 2

    @pytest.mark.parametrize("sub", sorted(__import__("lib.git_facts", fromlist=["x"]).GIT_READ_SUBCOMMANDS))
    def test_three_readers_agree(self, sub):
        from lib.bash_read_only import is_read_only
        hs = _load("pretool-harness-switch-guard.py")
        cg = _load("pretool-claude-config-guard.py")
        assert hs._read_only(["git", sub, "f"])
        assert sub in cg._GIT_READS
        assert is_read_only(f"git {sub}")
        assert not hs._read_only(["git", "stash", "push", "--", "f"])


class TestGitConfigReadWrite:
    """git-config-read-write: which `git config` forms read and which write."""

    READS = ["git config --get-urlmatch http https://example.invalid", "git config --get-color color.ui red",
             "git config --get-colorbool color.ui", "git config --get core.bare", "git config --list",
             "git config get core.bare", "git config list"]
    WRITES = ["git config --unset core.pager", "git config --add a.b c", "git config set a.b c",
              "git config unset a.b", "git config --rename-section a b", "git config --remove-section a"]

    @pytest.mark.parametrize("cmd", READS)
    def test_reads_agree(self, cmd):
        from lib.bash_read_only import is_read_only
        og = _load("pretool-overnight-hook-guard.py")
        args = cmd.split()[2:]
        assert is_read_only(cmd)
        assert og._config_reads(args)

    @pytest.mark.parametrize("cmd", WRITES)
    def test_writes_agree(self, cmd):
        from lib.bash_read_only import is_read_only
        og = _load("pretool-overnight-hook-guard.py")
        assert not is_read_only(cmd)
        assert not og._config_reads(cmd.split()[2:])

    def test_unset_is_a_write_for_userintent(self):
        """userintent counted `--unset` among the reads; it removes a setting (the pager git grep -O opens)."""
        from lib import git_facts
        assert "--unset" in git_facts.GIT_CONFIG_WRITE_OPTIONS
        assert not git_facts.GIT_CONFIG_WRITE_OPTIONS & git_facts.GIT_CONFIG_READ_OPTIONS
        ui = _load("pretool-wrapper-userintent.py")
        assert ui._GIT_CONFIG_READS == git_facts.GIT_CONFIG_READ_OPTIONS


class TestGitWorktreeDiscarders:
    """git-worktree-discarders: which git subcommands overwrite or remove the working-tree files they name.

    audit f04/f05: the config guard refused `git restore T` and passed `git clean -f T`, `git
    checkout-index -f T` and `git stash push -- T`, as did tool-policy and the views guard; the shared
    parser gave a write target only to checkout and restore."""

    @pytest.mark.parametrize("cmd,mode", [
        ("git clean -f t/x", "delete"), ("git clean -fd t/x", "delete"),
        ("git checkout-index -f t/x", "truncate"), ("git stash push -- t/x", "truncate"),
        ("git stash push -m wip t/x", "truncate"), ("git stash -- t/x", "truncate"),
        ("git restore t/x", "truncate"), ("git checkout HEAD~1 -- t/x", "truncate")])
    def test_shared_parser_names_the_file(self, cmd, mode):
        got = [(t.path, t.mode) for t in sp.write_targets(sp.parse(cmd))]
        assert got == [("t/x", mode)]

    @pytest.mark.parametrize("cmd", ["git clean -n -f t/x", "git clean t/x", "git stash", "git stash list",
                                     "git stash push -m wip", "git checkout-index -a -f"])
    def test_forms_that_name_no_file(self, cmd):
        assert sp.write_targets(sp.parse(cmd)) == []

    @pytest.mark.parametrize("cmd", ["git clean -f .claude/hooks/x.py", "git checkout-index -f .claude/hooks/x.py",
                                     "git stash push -- .claude/hooks/x.py", "git restore .claude/hooks/x.py"])
    def test_config_guard_refuses_each(self, scratch, cmd):
        assert run_hook(scratch, "pretool-claude-config-guard.py", cmd) == 2

    def test_runtime_guard_and_overnight_read_the_table(self):
        assert git_cmds._GIT_DESTRUCTIVE_SUBCMDS == sp.GIT_WORKTREE_DISCARDERS
        toks = ["git", "checkout-index", "-f", "a/b"]
        assert git_cmds._git_is_destructive_invocation(toks, 1, "checkout-index")
        assert not git_cmds._git_is_destructive_invocation(["git", "checkout-index", "a/b"], 1, "checkout-index")
        assert not git_cmds._git_is_destructive_invocation(["git", "stash", "push"], 1, "stash")


def _resolved(cmd):
    return sp.resolve(next(iter(sp.walk(sp.parse(cmd)))).cmd)


class TestGitRunOrWriteOptions:
    """git-exec-or-write-options: the subcommand options that run a program or write a file.

    The read-proving rules (the orchestrator's read-only gate, the config guard's settled read, the
    plain-git, http-reader, bulk and session_dirs rules) each refused a different subset; they now read
    git_facts.GIT_RUN_OR_WRITE_OPTIONS. The disk guard refuses only the options whose argument line
    names the program or file (GIT_ARGV_RUN_OR_WRITE_OPTIONS): a driver the configuration names runs
    for every git call it allows."""

    RUNS = ["git show --textconv HEAD:f", "git log --ext-diff -p", "git diff --output=o", "git grep -O x",
            "git log --exec=x", "git cat-file --filters HEAD:f"]

    @pytest.mark.parametrize("cmd", RUNS)
    def test_read_provers_agree(self, cmd):
        from lib.bash_read_only import is_read_only
        from lib import bash_safety_rules as bsr
        cg = _load("pretool-claude-config-guard.py")
        res = _resolved(cmd)
        assert not is_read_only(cmd)
        assert not cg._git_settled(res, cmd)
        assert not bsr._plain_git(list(res.args))
        assert not bsr._sd_plain_git([w.value() for w in res.args])

    @pytest.mark.parametrize("cmd", ["git show HEAD:f", "git log -p", "git diff"])
    def test_plain_reads_still_read(self, cmd):
        from lib.bash_read_only import is_read_only
        from lib import bash_safety_rules as bsr
        cg = _load("pretool-claude-config-guard.py")
        res = _resolved(cmd)
        assert is_read_only(cmd) and cg._git_settled(res, cmd) and bsr._plain_git(list(res.args))

    def test_disk_guard_set_is_the_argv_subset(self):
        from lib import bash_safety_rules as bsr, git_facts
        assert set(bsr._DG_GIT_ALL) == git_facts.GIT_ARGV_RUN_OR_WRITE_OPTIONS < git_facts.GIT_RUN_OR_WRITE_OPTIONS
        assert bsr._dg_git_runs(["git", "diff", "--output=o"]) and not bsr._dg_git_runs(["git", "log", "--textconv"])


class TestGitRemoteReadFlags:
    """git-remote-read-flags (undecided in the audit): the orchestrator's gate allowed --all/--push on
    `remote get-url` and -v/--verbose on a bare `remote`, the disk guard all five anywhere. One fact:
    each flag only reads where git takes it, and git refuses it (exit 129, nothing run) elsewhere."""

    @pytest.mark.parametrize("cmd", ["git remote -v", "git remote --verbose", "git remote get-url --all origin",
                                     "git remote get-url --push origin"])
    def test_both_read(self, cmd):
        from lib.bash_read_only import is_read_only
        from lib import bash_safety_rules as bsr
        words = cmd.split()
        assert is_read_only(cmd)
        assert bsr._dg_git(None, words)

    @pytest.mark.parametrize("cmd", ["git remote add x y", "git remote set-url origin y", "git remote -v rm x"])
    def test_both_refuse(self, cmd):
        from lib.bash_read_only import is_read_only
        from lib import bash_safety_rules as bsr
        assert not is_read_only(cmd)
        assert not bsr._dg_git(None, cmd.split())


def test_git_rm_options_one_definition():
    """git-rm-options (undecided in the audit, "7 of 12 names common"): the removal policy's spec held
    rm's short options beside the same eight long ones shell_parse lists; it now reads shell_parse's."""
    from lib import bash_execution_boundary as beb
    longs = {o for o in beb.GIT_RM["bool"] | beb.GIT_RM["val"] if o.startswith("--")}
    assert longs == set(sp.GIT_LONG_OPTIONS["rm"])
