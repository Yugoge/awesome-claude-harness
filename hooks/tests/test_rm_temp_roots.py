"""A plain `rm` of paths inside a temp root clears the removal policy; everything around it stays refused.

Owner decision (lane rm-temp): every role may remove (rm, -r, -f, -rf) paths under /tmp, /var/tmp,
$TMPDIR and its own scratch directories. hooks/lib/bash_execution_boundary.py allows such an `rm` as
PROVEN_SAFE_REMOVAL `temp_root_removal` only when the analyzer can prove each target: written as its
command's own head at the top level (no wrapper, nested shell, alias or variable assignment), only
the rm options it knows, every operand a literal absolute path (a glob only in the last component,
checked against each entry it could match), the resolved path and the directory entry both strictly
below a temp root (hooks/lib/harness_temp_state.py, the one definition), not harness control state,
nothing protected at or below it (a temp root, a state name root, the state dir, a harness home,
the project dir, a .git) and no control state among its entries. Anything else keeps the refusal it
had: FORBIDDEN_REMOVAL `filesystem_removal`.

The system temp roots are swapped for directories under tmp_path, so no test reads or removes the
real /tmp or /var/tmp; the last class runs the registered PreToolUse pipeline in a scratch HOME.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "hooks" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import bash_execution_boundary as eb  # noqa: E402
import harness_temp_state as hts  # noqa: E402

ENV_VARS = ("CLAUDE_STATE_DIR", "TMPDIR", "CLAUDE_TMPDIR", "CLAUDE_CODE_TMPDIR", "XDG_RUNTIME_DIR",
            "CLAUDE_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR") + hts.NAME_ROOT_VARS + tuple(
    var for loc in hts.LOCATIONS for var in loc.tree_vars)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Fake /tmp, /var/tmp and $TMPDIR; HOME and the harness home live outside them."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    tmp, var_tmp = tmp_path / "tmp", tmp_path / "var" / "tmp"
    tmpdir = tmp / "claude-0"  # the agent's TMPDIR, nested in /tmp as Claude Code sets it
    outside, home = tmp_path / "outside", tmp_path / "home"
    for d in (tmp, var_tmp, tmpdir, outside, home / ".claude"):
        d.mkdir(parents=True)
    monkeypatch.setattr(hts, "SYSTEM_TEMP_ROOTS", (str(tmp), str(var_tmp)))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp))
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("HOME", str(home))
    return {"tmp": tmp, "var_tmp": var_tmp, "tmpdir": tmpdir, "outside": outside, "home": home}


def _verdict(cmd):
    out = eb.analyze(cmd)
    return out["allowed"], out["verdict"], out["reason"]


def allowed(cmd):
    ok, verdict, reason = _verdict(cmd)
    assert ok and verdict == eb.PROVEN_SAFE_REMOVAL and reason.startswith("temp_root_removal"), (
        cmd, verdict, reason)


def refused(cmd):
    ok, verdict, reason = _verdict(cmd)
    assert not ok and verdict in (eb.FORBIDDEN_REMOVAL, eb.UNRESOLVED), (cmd, verdict, reason)


def _work(root, name="work"):
    d = root / name
    (d / "sub").mkdir(parents=True)
    (d / "a.csv").write_text("x")
    (d / "b.csv").write_text("y")
    (d / "sub" / "c.txt").write_text("z")
    return d


# -- the lifted over-block (red on the base, green here) ------------------------------------------

def test_the_owner_example_rm_f_of_a_csv_in_tmp(roots):
    allowed("rm -f %s/q.csv" % roots["tmp"])


def test_the_owner_example_with_the_real_system_roots(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_STATE_DIR", "/tmp")
    allowed("rm -f /tmp/rm-temp-lane-q-%d.csv" % os.getpid())


@pytest.mark.parametrize("flags", ["-r", "-f", "-rf", "-fr", "-R", "-r -f", "--recursive --force",
                                   "-rfv", "-rf --one-file-system", "-d", "--preserve-root -rf"])
def test_every_flag_spelling_of_a_temp_directory_removal(roots, flags):
    allowed("rm %s %s" % (flags, _work(roots["tmp"])))


@pytest.mark.parametrize("where", ["tmp", "var_tmp", "tmpdir"])
def test_each_temp_root(roots, where):
    allowed("rm -rf %s" % _work(roots[where]))


def test_the_agents_scratch_dir_under_tmpdir(roots):
    scratch = roots["tmpdir"] / "-home-user-proj" / "session-1" / "scratchpad"
    scratch.mkdir(parents=True)
    (scratch / "out.json").write_text("{}")
    allowed("rm -rf %s" % scratch)
    allowed("rm -f %s/out.json" % scratch)


def test_harness_scratch_kind_is_removable(roots):
    d = roots["tmp"] / "claude-scratch" / "sess-1" / "notes"
    d.mkdir(parents=True)
    allowed("rm -rf %s" % d)
    allowed("rm -rf %s/codex-outputs" % roots["tmp"])


def test_several_operands_double_dash_and_a_missing_file(roots):
    w = _work(roots["tmp"])
    allowed("rm -rf -- %s %s/nope.txt" % (w, roots["var_tmp"]))
    allowed("rm %s/a.csv %s/b.csv" % (w, w))
    allowed("rm -f '%s/a b.csv'" % w)


def test_a_final_component_glob_inside_a_temp_dir(roots):
    w = _work(roots["tmp"])
    allowed("rm -f %s/*.csv" % w)
    allowed("rm -rf %s/*" % w)
    allowed("rm -f %s/[ab].csv %s/?.csv" % (w, w))
    allowed("rm -rf %s/none-*" % w)  # no match: rm is handed the literal pattern


def test_inside_ordinary_control_flow_at_top_level(roots):
    w = _work(roots["tmp"])
    allowed("cd /; rm -rf %s && echo done" % w)
    allowed("if true; then rm -f %s/a.csv; fi" % w)
    allowed("ls %s | wc -l; rm -rf %s" % (w, w))


# -- dangerous neighbours stay refused --------------------------------------------------------------

@pytest.mark.parametrize("name", ["claude-grants", "claude-grants/g.json", "claude-orchestrator-consent-s1.flag",
                                  "claude-commit-grant-s1-a.json", "claude-push-grant-s1-a.json",
                                  "agentic-commit", "agentic-commit/push/x/token.json",
                                  "claude-commit-manifest-s1.json", "claude-git-blessed",
                                  "claude-capability-s1", "claude-do-resv-1"])
def test_harness_control_state(roots, name):
    p = roots["tmp"] / name
    refused("rm -rf %s" % p)
    refused("rm -f %s" % p)
    refused("rm -rf %s/%s" % (roots["tmpdir"], name))


def test_a_directory_holding_control_state(roots):
    owned = roots["tmp"] / "role-scratch"
    owned.mkdir()
    (owned / ".owner").write_text("sid")
    refused("rm -rf %s" % owned)
    refused("rm -f %s/.owner" % owned)
    refused("rm -rf %s/*" % owned)  # the glob could match .owner
    sess = roots["tmp"] / "claude-scratch" / "sess-1"
    sess.mkdir(parents=True)
    (sess / ".owner").write_text("sid")
    refused("rm -rf %s" % sess)
    refused("rm -rf %s/claude-scratch" % roots["tmp"])


def test_a_directory_holding_the_state_dir_or_a_temp_root(roots, monkeypatch):
    refused("rm -rf %s" % roots["tmpdir"])  # $TMPDIR itself
    state = roots["tmp"] / "work" / "state"
    state.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    refused("rm -rf %s/work" % roots["tmp"])
    refused("rm -rf %s" % state)


@pytest.mark.parametrize("cmd", ["rm -rf {tmp}", "rm -rf {var_tmp}", "rm -rf {tmpdir}", "rm -rf {tmp}/",
                                 "rm -rf {tmp}/.", "rm -rf {tmp}/*", "rm -rf {var_tmp}/*", "rm -f {tmp}/claude-*"])
def test_a_temp_root_itself_or_a_sweep_of_one(roots, cmd):
    refused(cmd.format(**roots))


@pytest.mark.parametrize("cmd", ["rm -rf {tmp}/../outside", "rm -rf {tmp}/work/../../outside",
                                 "rm -rf -- {tmp}/../outside", "rm -rf {tmp}/./work", "rm -rf {tmp}/work/.."])
def test_dot_dot_and_dot(roots, cmd):
    _work(roots["tmp"])
    refused(cmd.format(**roots))


def test_paths_outside_and_relative_paths(roots):
    refused("rm -f %s/x" % roots["outside"])
    refused("rm -rf /etc")
    refused("rm -rf /")
    refused("rm -f q.csv")
    refused("rm -rf .")
    refused("rm -rf ..")
    refused("rm -rf ~")
    refused("rm -rf ~/x")
    refused("rm -rf %s/ok /etc/passwd" % roots["tmp"])  # one failing target refuses the command


def test_symlinks_out_of_a_temp_root(roots):
    out = roots["outside"] / "precious"
    out.mkdir()
    link = roots["tmp"] / "link"
    link.symlink_to(out)
    refused("rm -rf %s" % link)
    refused("rm -rf %s/" % link)
    refused("rm -rf %s/x" % link)
    (roots["tmp"] / "lnstate").symlink_to(roots["tmp"] / "claude-grants")
    refused("rm -rf %s/lnstate" % roots["tmp"])
    # an entry outside a temp root pointing in is still outside
    back = roots["outside"] / "in"
    back.symlink_to(_work(roots["tmp"]))
    refused("rm -f %s" % back)


@pytest.mark.parametrize("cmd", ["rm -rf $TMPDIR/x", 'rm -rf "$TMPDIR"', "rm -rf ${{HOME}}", "rm -rf $HOME/x",
                                 "rm -rf $(echo {tmp}/x)", "rm -rf `echo {tmp}/x`", "rm -rf {tmp}/{{a,b}}",
                                 "rm -rf {tmp}/*/x", "rm -rf {tmp}/w*/../x", "rm -rf {tmp}/work/**",
                                 "rm -rf {tmp}/work/@(a|b)", "rm -rf {tmp}/$X", "X={tmp}/a; rm -rf $X"])
def test_variables_substitutions_braces_and_wide_globs(roots, cmd):
    _work(roots["tmp"])
    refused(cmd.format(**roots))


@pytest.mark.parametrize("cmd", ["rm -- -rf /", "rm -rf -- {tmp}/../etc", "rm -rf / --no-preserve-root",
                                 "rm --no-preserve-root -rf {tmp}/work", "rm --no-pres -rf {tmp}/work",
                                 "rm --interactive=never -rf {tmp}/work", "rm -rf --help {tmp}/work",
                                 "rm -x {tmp}/work", "rm -rf", "rm -- {tmp}/../outside"])
def test_option_and_double_dash_tricks(roots, cmd):
    _work(roots["tmp"])
    refused(cmd.format(**roots))


@pytest.mark.parametrize("cmd", ["xargs rm -rf {tmp}/work", "echo {tmp}/work | xargs rm -rf",
                                 "find {tmp}/work -delete", "env rm -rf {tmp}/work", "sudo rm -rf {tmp}/work",
                                 "command rm -rf {tmp}/work", "nohup rm -rf {tmp}/work", "time rm -rf {tmp}/work",
                                 "exec rm -rf {tmp}/work", "bash -c 'rm -rf {tmp}/work'", "echo $(rm -rf {tmp}/work)",
                                 "eval 'rm -rf {tmp}/work'", "/bin/rm -rf {tmp}/work", "./rm {tmp}/work",
                                 "unlink {tmp}/work/a.csv", "shred -u {tmp}/work/a.csv", "FOO=1 rm -rf {tmp}/work",
                                 "PATH=/x rm -rf {tmp}/work", "export X=1; rm -rf {tmp}/work",
                                 "alias rm='rm -rf /'; rm {tmp}/work"])
def test_wrappers_and_other_front_ends(roots, cmd):
    _work(roots["tmp"])
    refused(cmd.format(**roots))


def test_harness_home_settings_and_home_claude(roots, monkeypatch):
    home = roots["tmp"] / "h"
    claude = home / ".claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "settings.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    refused("rm -rf %s" % claude)
    refused("rm -f %s/settings.json" % claude)
    refused("rm -rf %s/hooks" % claude)
    refused("rm -rf %s" % home)  # holds ~/.claude
    cfg = roots["tmp"] / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    refused("rm -rf %s" % cfg)
    monkeypatch.setenv("CLAUDE_HOME", str(roots["var_tmp"] / "ch"))
    refused("rm -rf %s/ch/hooks" % roots["var_tmp"])


def test_this_harness_home_its_hooks_and_git(monkeypatch, tmp_path):
    # The tree these hooks run from counts as a harness home wherever it sits, even inside a temp root.
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(hts, "SYSTEM_TEMP_ROOTS", (str(ROOT.parent),))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path))
    refused("rm -f %s/hooks/pretool-bash-safety.sh" % ROOT)
    refused("rm -f %s/settings.json" % ROOT)
    refused("rm -rf %s/.git" % ROOT)
    refused("rm -rf %s" % ROOT)


def test_the_project_dir_and_any_git_dir(roots, monkeypatch):
    proj = roots["tmp"] / "proj"
    (proj / ".git" / "objects").mkdir(parents=True)
    (proj / "build").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    refused("rm -rf %s/.git" % proj)
    refused("rm -rf %s/.git/objects" % proj)
    refused("rm -rf %s" % proj)
    refused("rm -rf %s/build" % proj)
    other = roots["tmp"] / "clone"
    (other / ".git").mkdir(parents=True)
    refused("rm -rf %s/.git" % other)


# -- through the registered PreToolUse pipeline ----------------------------------------------------

sys.path.insert(0, str(ROOT))
from tests.replay import sites  # noqa: E402


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Every PreToolUse hook settings.json registers for Bash, run alone in a scratch HOME (as
    hooks/tests/test_c_layer_protected_targets.py runs them), with a scratch state dir and TMPDIR."""
    base = tmp_path_factory.mktemp("rm-temp-pipeline")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmpdir"
    for d in (home, state, repo, tmp):
        d.mkdir(parents=True)
    config = home / ".claude"
    shutil.copytree(ROOT, config, symlinks=True,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", ".git", ".pytest_cache"))
    gitconfig = base / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(config), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_HOOK_BOUNDARY_TIMEOUT": "60s"}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    settings = sites.expand_launchers(str(ROOT), json.loads((config / "settings.json").read_text()))
    hooks = []
    for entry in settings["hooks"]["PreToolUse"]:
        matcher = entry.get("matcher")
        if matcher in (None, "", "*") or re.fullmatch(matcher, "Bash"):
            for h in entry["hooks"]:
                name = re.search(r"/hooks/([^/\"]+)\"?\s*$", h["command"]).group(1)
                rules = [r.file[len("hooks/"):] for r in sites.gate_rules(str(ROOT), "hooks/" + name)
                         if r.relays and (r.tools is None or "Bash" in r.tools)]
                hooks += rules or [name]
    work = tmp / "work"
    (work / "sub").mkdir(parents=True)
    (work / "a.csv").write_text("x")
    (state / "claude-grants").mkdir()
    return {"env": env, "repo": str(repo), "hooks_dir": config / "hooks", "hooks": hooks,
            "tmp": tmp, "state": state, "config": config}


def _run(p, hook, command, subagent, n):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "rm-temp-%d" % n,
               "cwd": p["repo"], "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-rm-temp-test", agent_type="dev")
    argv = ["bash" if hook.endswith(".sh") else sys.executable, str(p["hooks_dir"] / hook)]
    proc = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          env=p["env"], cwd=p["repo"], timeout=300)
    return proc.returncode, proc.stderr


def _pipeline(p, command, subagent):
    return {hook: _run(p, hook, command, subagent, n) for n, hook in enumerate(p["hooks"])}


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "dev"])
@pytest.mark.parametrize("cmd", ["rm -f {tmp}/q.csv", "rm -rf {tmp}/work", "rm -rf {tmp}/work/*.csv"])
def test_pipeline_allows_a_temp_removal(pipeline, cmd, subagent):
    assert "pretool-bash-safety.sh" in pipeline["hooks"]
    results = _pipeline(pipeline, cmd.format(tmp=pipeline["tmp"]), subagent)
    blocked = {h: r for h, r in results.items() if r[0] != 0}
    assert not blocked, blocked


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "dev"])
@pytest.mark.parametrize("cmd", ["rm -rf {tmp}/../repo", "rm -rf {state}/claude-grants", "rm -rf {tmp}",
                                 "rm -f {config}/settings.json", "xargs rm -rf {tmp}/work",
                                 "rm -rf $TMPDIR/work", "sudo rm -rf {tmp}/work"])
def test_pipeline_still_refuses_the_neighbours(pipeline, cmd, subagent):
    command = cmd.format(tmp=pipeline["tmp"], state=pipeline["state"], config=pipeline["config"])
    code, err = _run(pipeline, "pretool-bash-safety.sh", command, subagent, 0)
    assert code == 2 and "removal-policy" in err, (command, code, err)
