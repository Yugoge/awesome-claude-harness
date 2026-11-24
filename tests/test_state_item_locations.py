"""Writer and reader of each state item resolve to the same place (location audit, f199dfb1e).

One row per item of the audit's "can_disagree" verdict (state_items.json): the row runs the code
that builds the path on each side -- the repository's own function or script line, or, for a side
outside the repository (the owner's helper, the Claude Code CLI, the paseo daemon, Codex), the rule
that side follows, cited -- in the environments the audit names, and returns (label, writer, reader)
pairs. The test fails when any pair differs.

Situations, built under tmp_path, nothing outside it is written:
  a  this machine: harness home H, HOME/.claude -> H, one configuration directory per session whose
     settings.json links to HOME/.claude/settings.json; sessions get CLAUDE_CONFIG_DIR, CLAUDE_HOME,
     TMPDIR/CLAUDE_CODE_TMPDIR (the committed settings) and the optional CLAUDE_CONFIG_DIRS list; the owner's
     terminal gets HOME and XDG_RUNTIME_DIR only.
  b  default install: HOME/.claude is the harness home, no CLAUDE_CONFIG_DIR.
  c  the same under a non-root user's home; the uid is the runner's.
CLAUDE_STATE_DIR points into tmp_path on every side, so no state lands in the real /tmp.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HANG_GUARD = 900  # seconds: a bound only a hung child reaches (see test_scratch_permissions)
HOOKS, LIB, SCRIPTS = REPO / "hooks", REPO / "hooks" / "lib", REPO / "scripts"
SID = "0e0e0e0e-1111-4222-8333-444455556666"
SETTINGS_TMP = json.loads((REPO / "settings.json").read_text())["env"]["CLAUDE_CODE_TMPDIR"]


def _run(argv, env, cwd=None):
    proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=HANG_GUARD)
    if proc.returncode != 0:
        raise AssertionError(f"{argv[:3]} rc={proc.returncode}: {proc.stderr.strip()[-600:]}")
    return proc.stdout.strip()


def py(code, env, cwd=None):
    head = f"import sys; sys.path[:0] = [{str(LIB)!r}, {str(HOOKS)!r}]\n"
    return _run([sys.executable, "-c", head + code], env, cwd)


def sh(code, env, cwd=None):
    return _run(["bash", "-c", code], env, cwd)


def script_fn(path, call):
    """Python that loads a repository script as a module (not __main__) and prints call(ns)."""
    return f"import runpy; ns = runpy.run_path({str(path)!r}, run_name='audit'); print({call})"


def real(p):
    return os.path.realpath(p) if p and p != "None" else p


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state, self.run_dir, self.scratch = tmp / "state", tmp / "run", tmp / "scratch"
        for d in (self.state, self.run_dir, self.scratch):
            d.mkdir()
        self.harness = tmp / "a" / "harness"
        self.harness.mkdir(parents=True)
        (self.harness / "settings.json").write_text("{}\n")
        self.homes = {"a": tmp / "a" / "root", "b": tmp / "b" / "root", "c": tmp / "c" / "home" / "user"}
        self.homes["a"].mkdir(parents=True)
        (self.homes["a"] / ".claude").symlink_to(self.harness)
        for s in "bc":
            (self.homes[s] / ".claude").mkdir(parents=True)
            (self.homes[s] / ".claude" / "settings.json").write_text("{}\n")
        self.configs = {name: tmp / "a" / f"config-{name}" for name in ("one", "two")}
        for cfg in self.configs.values():
            (cfg / "projects").mkdir(parents=True)
            (cfg / "settings.json").symlink_to(self.homes["a"] / ".claude" / "settings.json")

    def base(self, s):
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.homes[s]), "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1", "CLAUDE_STATE_DIR": str(self.state)}

    def session(self, s, cfg="one", **extra):
        env = {**self.base(s), "TMPDIR": str(self.scratch), "CLAUDE_CODE_TMPDIR": str(self.scratch),
               "CLAUDECODE": "1"}
        if s == "a":
            env.update(CLAUDE_CONFIG_DIR=str(self.configs[cfg]), CLAUDE_HOME=str(self.harness),
                       CLAUDE_CONFIG_DIRS=os.pathsep.join(str(c) for c in self.configs.values()))
        env.update(extra)
        return {k: v for k, v in env.items() if v is not None}

    def terminal(self, s, **extra):
        env = {**self.base(s), "XDG_RUNTIME_DIR": str(self.run_dir), **extra}
        return {k: v for k, v in env.items() if v is not None}

    def contexts(self, s):
        """(label, environment) of every context that writes or reads a per-harness record."""
        out = [(f"{s}/session", self.session(s)), (f"{s}/terminal", self.terminal(s))]
        if s == "a":
            out.insert(1, ("a/session config-two", self.session("a", "two")))
        return out


def same_everywhere(w, expr):
    """Pairs that compare the first context's value of `expr` with every other context's."""
    pairs = []
    for s in "abc":
        ctx = w.contexts(s)
        first = py(expr, ctx[0][1])
        pairs += [(f"{ctx[0][0]} vs {label}", real(first), real(py(expr, env))) for label, env in ctx[1:]]
    return pairs


# ---------------------------------------------------------------------------------------------- rows

def s01(w):
    # writer: the owner's daemon-restart grant helper (outside the repository): SENTINEL_DIR="${CLAUDE_DAEMON_RESTART_SENTINEL_DIR:-/tmp}",
    # run from the owner's terminal; reader: the PreToolUse hook's environment()["grant_dir"] in a session.
    reader = "import bash_safety_rules as b; print(b.environment()['grant_dir'])"
    return [(s, sh('printf %s "${CLAUDE_DAEMON_RESTART_SENTINEL_DIR:-/tmp}"', w.terminal(s)),
             py(reader, w.session(s))) for s in "abc"]


def p01(w):
    pairs = []
    for s in "abc":
        project = w.tmp / s / "proj.x"
        (project / ".claude").mkdir(parents=True, exist_ok=True)
        hook = w.session(s, CLAUDE_PROJECT_DIR=str(project))
        writer = py(script_fn(HOOKS / "prompt-workflow.py", f"ns['workflow_bookmark_path']({SID!r}).parent"),
                    hook, cwd=project)
        accounts = w.tmp / s / "prune-root"  # the pruner's own <dir>/<name>/claude/projects scan
        (accounts / "x" / "claude").mkdir(parents=True, exist_ok=True)
        out = sh(f'bash {SCRIPTS / "prune-orphaned-workflow-bookmarks.sh"!s}',
                 w.session(s, WORKFLOW_PRUNE_ACCOUNTS_DIR=str(accounts)), cwd=project)
        scanned = re.search(r"^(?:Repo root|Bookmark directory): (.*)$", out, re.M).group(1)
        folder = re.search(r"^Project dirname: (.*)$", out, re.M).group(1)
        pairs += [(f"{s} bookmark dir", real(writer), real(scanned)),
                  (f"{s} transcript folder", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(project)), folder)]
    return pairs


def r1(w):
    git = {**w.base("a"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    top = w.tmp / "repo"
    sub = top / "frontend"
    sub.mkdir(parents=True)
    sh("git init -q .", git, cwd=top)
    text = (REPO / "commands" / "dev.md").read_text()
    expr = re.search(r'--project-dir "(\$\{CLAUDE_PROJECT_DIR:-[^"]*\})"', text).group(1)
    pairs = []
    for s in "abc":
        bash = w.session(s)  # the Bash tool: no CLAUDE_PROJECT_DIR, cwd = the session's directory
        pairs.append((f"{s} commands/dev.md", str(sub), real(sh(f'printf %s "{expr}"', bash, cwd=sub))))
        for script in ("resolve-dev-artifact-chain.py", "dev-lifecycle.py"):
            got = py(script_fn(SCRIPTS / script, "ns['_default_project_dir']()"), bash, cwd=sub)
            pairs.append((f"{s} {script}", str(sub), real(got)))
        # Steps that run without hooks/lib spell the rule themselves: pinned to locations.project_root(bash=True).
        rule = py("import locations; print(locations.project_root(bash=True))", bash, cwd=sub) \
            if (LIB / "locations.py").is_file() else str(sub)
        for script, call in (("steps/spec-capture.py", "ns['project_dir'](None)"),
                             ("steps/spec-finalize.py", "ns['project_dir'](None)"),
                             ("aggregate-dev-report.py", "ns['_resolve_project_root'](None)")):
            pairs.append((f"{s} {script}", real(rule), real(py(script_fn(SCRIPTS / script, call), bash, cwd=sub))))
    return pairs


def c04(w):
    return same_everywhere(w, "import score_log; print(score_log.log_path())")


def c01(w):
    cfg = w.configs["one"] / "projects" / "-work"
    cfg.mkdir(parents=True, exist_ok=True)  # the CLI: <config dir>/projects/<folder>/<session>.jsonl
    (cfg / f"{SID}.jsonl").write_text(json.dumps({"type": "user", "cwd": "/work", "sessionId": SID}) + "\n")
    lookup = script_fn(SCRIPTS / "capability-doctor-strict.py", f"ns['_transcript_cwd']({SID!r})")
    return [(label, "/work", py(lookup, env)) for label, env in
            (("config-one session", w.session("a")), ("config-two session", w.session("a", "two")))]


def t07(w):
    # writer: the CLI, <CLAUDE_CODE_TMPDIR, else TMPDIR, else /tmp>/claude-<uid>/<project>/<session>/tasks/*.output,
    # in the environment the committed settings give it. reader: the sweep's CLI_DIRS, built by its own root setup
    # in the environment it runs in (the cron file's, or the session's at the pressure hook), of its own uid.
    script = SCRIPTS / "install" / "tmp-cleanup-install.sh"
    setup = re.search(r'^HARNESS_HOME=.*?^\[ -n "\$CLI_ROOT" \][^\n]*$', script.read_text(), re.M | re.S).group(0)
    cron = dict(re.findall(r"^(\w+)=(.*)$", (SCRIPTS / "install" / "tmp-cleanup.cron").read_text(), re.M))
    pairs = [("cron CLAUDE_CODE_TMPDIR vs settings", SETTINGS_TMP, cron.get("CLAUDE_CODE_TMPDIR"))]
    for label, extra in (("CLAUDE_CODE_TMPDIR set", {"CLAUDE_CODE_TMPDIR": "t07-cli", "TMPDIR": "t07-other"}),
                         ("TMPDIR only", {"TMPDIR": "t07-tmp"})):
        env = w.terminal("b", **{k: str(w.tmp / v) for k, v in extra.items()})
        writer = str(w.tmp / next(iter(extra.values())) / f"claude-{os.getuid()}")
        os.makedirs(writer)
        reader = _run(["bash", "-c", setup + '\nprintf "%s\\n" "${CLI_DIRS[@]}"', str(script)], env)
        pairs.append((label, real(writer), real(reader)))
    return pairs


def c13(w):
    # The sealer's harness tree is this repository: configuration directories whose settings.json links to
    # its settings.json, and a terminal whose ~/.claude is it.
    home = w.tmp / "c13-home"
    home.mkdir()
    (home / ".claude").symlink_to(REPO)
    expr = script_fn(SCRIPTS / "seal-attribution-journal.py", "ns['default_dest']()")
    pairs, first = [], None
    for name in ("one", "two"):
        cfg = w.tmp / f"c13-config-{name}"
        cfg.mkdir()
        (cfg / "settings.json").symlink_to(home / ".claude" / "settings.json")
        got = real(py(expr, w.session("a", CLAUDE_CONFIG_DIR=str(cfg), HOME=str(home))))
        first = first or got
        pairs.append((f"session config-{name}", first, got))
    pairs.append(("terminal", first, real(py(expr, w.terminal("a", HOME=str(home))))))
    for s in "bc":  # a default install: one configuration directory, the harness home
        pairs.append((f"{s} session vs terminal", py(expr, w.terminal(s)), py(expr, w.session(s))))
    return pairs


def c06(w):
    # writer: hooks/git-fswatch.sh run by git-fswatch@.service (HOME only); reader: fswatch-manager.sh `logs`.
    pairs = []
    for s in "abc":
        writer = sh(f'. {HOOKS / "lib" / "harness_state_dir.sh"!s} 2>/dev/null; REPO_NAME=repo; '
                    f'eval "$(grep -E "^LOG_FILE=" {HOOKS / "git-fswatch.sh"!s})"; printf %s "${{LOG_FILE%/*}}"',
                    {"PATH": os.environ["PATH"], "HOME": str(w.homes[s])})
        out = subprocess.run(["bash", str(HOOKS / "fswatch-manager.sh"), "logs", "/x"], env=w.session(s),
                             capture_output=True, text=True, timeout=HANG_GUARD).stdout
        reader = re.search(r"No log file found: (\S+)/git-fswatch-", out).group(1)
        pairs.append((s, real(writer), real(reader)))
    return pairs


def c05(w):
    expr = f'. {LIB / "checkpoint-core.sh"!s} >/dev/null 2>&1; printf %s "$CHECKPOINT_LOG_DIR"'
    pairs = []
    for s in "abc":
        ctx = w.contexts(s)
        first = sh(expr, ctx[0][1])
        pairs += [(f"{ctx[0][0]} vs {label}", real(first), real(sh(expr, env))) for label, env in ctx[1:]]
    return pairs


def s29(w):
    expr = f"import capability_state as cs; print(cs.state_path({SID!r}))"
    return [(s, py(expr, w.terminal(s)), py(expr, w.session(s))) for s in "abc"]


def c12(w):
    cfg = w.tmp / "config-of-repo"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").symlink_to(REPO / "settings.json")
    out = subprocess.run([sys.executable, str(SCRIPTS / "harness-switch"), "status"],
                         env=w.session("a", CLAUDE_CONFIG_DIR=str(cfg)), capture_output=True, text=True,
                         timeout=HANG_GUARD).stdout
    line = next(l for l in out.splitlines() if l.startswith("Config dir:"))
    decided = str(REPO.resolve()) if "not this home" not in line else str(cfg)
    return [("CLI loads", os.path.dirname(os.path.realpath(cfg / "settings.json")), decided)]


def c03(w):
    return same_everywhere(w, "import subagent_restart as r; print(r.state_dir())")


def r2(w):
    # One configuration directory per session here: a record the CLI keeps in config-one is still found by
    # the handshake's transcript snapshot run in a config-two session (CLAUDE_CONFIG_DIRS names both).
    cfg = w.configs["one"] / "projects" / "-work"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / f"{SID}.jsonl").write_text("{}\n")
    seen = py(script_fn(SCRIPTS / "capability-handshake.py", "sorted(ns['transcript_offsets']())"),
              w.session("a", "two"))
    writer = str(cfg / f"{SID}.jsonl")
    return [("config-two session", writer, writer if writer in seen else seen)]


def s02(w):
    over = w.tmp / "sentinels"
    over.mkdir()
    env = w.session("a", CLAUDE_USERINTENT_SENTINEL_DIR=str(over), CLAUDE_PROJECT_DIR=str(w.tmp))
    writer = py(script_fn(HOOKS / "prompt-workflow.py",
                          f"(ns['_write_userintent_sentinel']('stop', {SID!r}), "
                          f"[str(p.parent) for p in __import__('pathlib').Path({str(w.tmp)!r}).rglob("
                          f"'claude-stop-userintent-{SID}.flag')])[1][0]"), env, cwd=w.tmp)
    reader = py(script_fn(HOOKS / "pretool-wrapper-userintent.py", "ns['_SENTINEL_DIR']"), env, cwd=w.tmp)
    return [("override set", real(writer), real(reader))]


def p02(w):
    env = w.session("a", OVERNIGHT_STATE_SUBDIR=".ov")
    text = (SCRIPTS / "create-overnight-state.sh").read_text()
    sub = sh(re.search(r"^STATE_SUBDIR=.*$", text, re.M).group(0) + '; printf %s "$STATE_SUBDIR"', env)
    reader = py(f"import overnight; print(overnight.state_path({SID!r}, '/p').parent)", env)
    return [("override set", f"/p/{sub}", reader)]


def t02(w):
    from tests.test_scratch_permissions import script_root  # the root the start hook really uses, from its run
    (w.scratch / "outer").mkdir()
    (w.scratch / "outer" / ".owner").write_text('{"sid": "outer"}')
    (w.tmp / "link").symlink_to(w.scratch / "outer")
    pairs = []
    for label, tmpdir in (("TMPDIR absent", None), ("TMPDIR a session's dir, trailing slash", f"{w.scratch}/outer/"),
                          ("TMPDIR a session's dir through a link", str(w.tmp / "link"))):
        env = w.session("a", TMPDIR=tmpdir)
        probe = w.tmp / f"t02-probe-{len(pairs)}"
        probe.mkdir()
        writer = script_root(HOOKS / "session-scratch-init.sh", env, probe)
        reader = py("from doc_sync import notice; print(notice._state_root())", env)
        pairs.append((label, writer, reader))
    return pairs


def s34(w):
    env = w.terminal("a", CLAUDE_STATE_DIR=str(w.state))
    writer = py("from harness_state_dir import harness_state_dir; print(harness_state_dir())", env)
    text = (SCRIPTS / "install" / "tmp-cleanup-install.sh").read_text()
    # the sweep sources the shell resolver of its harness home (this tree when run from it)
    case = re.search(r'^\. "\$HARNESS_HOME/hooks/lib/harness_state_dir\.sh" && STATE_DIR=.*$', text, re.M)
    hook_state = re.search(r'^(\[ -z "\$STATE_DIR" \] \|\| SWEEP_ROOT="\$STATE_DIR" )?run_tmp "hook state', text, re.M)
    reader = (sh(f'HARNESS_HOME="{REPO}"; ' + case.group(0) + '; printf %s "$STATE_DIR"', env)
              if case and hook_state.group(1) else "/tmp")
    return [("CLAUDE_STATE_DIR set", writer, reader)]


def c10(w):
    paseo = w.tmp / "paseo-home"
    env = w.session("a", PASEO_HOME=str(paseo))  # the daemon: <PASEO_HOME>/schedules
    reader = py(script_fn(SCRIPTS / "paseo-daemon-timers.py", "ns['build_parser']().parse_args(['status']).registry_dir"),
                env)
    return [("PASEO_HOME set", str(paseo / "schedules"), reader)]


def c11(w):
    text = (SCRIPTS / "paseo-usage-read.mjs").read_text()
    names = re.findall(r"process\.env\.(\w+)", re.search(r"^const configDir = (.*);$", text, re.M).group(1))
    paseo = w.tmp / "paseo-home"
    env = w.session("a", PASEO_HOME=str(paseo))  # the daemon keeps config.json under its home
    reader = next((env[n] for n in names if env.get(n)), str(w.homes["a"] / ".paseo"))
    return [("PASEO_HOME set", str(paseo), reader)]


def p04(w):
    project = w.tmp / "cp-project"
    (project / ".claude").mkdir(parents=True)
    (project / ".git").mkdir()
    (project / "pkg").mkdir()
    got = py(script_fn(SCRIPTS / "spec-check.py", "ns['_project_dir']()"), w.session("a"), cwd=project / "pkg")
    return [("cd pkg", str(project), real(got))]  # the reader: CLAUDE_PROJECT_DIR = the project


def c09(w):
    codex = w.tmp / "codex-home"
    rollout = codex / "sessions" / "2026" / f"rollout-x-{SID}.jsonl"  # Codex: <CODEX_HOME>/sessions/**
    rollout.parent.mkdir(parents=True)
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": SID, "session_id": SID}}) + "\n")
    got = py(script_fn(HOOKS / "pretool-workflow-gate.py", f"ns['_transcript_path']({{}}, {SID!r})"),
             w.session("a", CODEX_HOME=str(codex)))
    return [("CODEX_HOME set", str(rollout.resolve()), got)]


ROWS = {"S01": s01, "P01": p01, "R1": r1, "C04": c04, "C01": c01, "T07": t07, "C13": c13, "C06": c06,
        "C05": c05, "S29": s29, "C12": c12, "R2": r2, "C03": c03, "S02": s02, "P02": p02, "T02": t02, "S34": s34,
        "C10": c10, "P04": p04, "C09": c09, "C11": c11}


@pytest.mark.parametrize("item", list(ROWS))
def test_writer_and_reader_resolve_to_the_same_place(tmp_path, item):
    pairs = ROWS[item](World(tmp_path))
    differ = [p for p in pairs if p[1] != p[2]]
    assert pairs and not differ, "\n".join(f"{label}: writer {a} | reader {b}" for label, a, b in differ)
