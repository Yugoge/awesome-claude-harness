#!/usr/bin/env python3
"""The /stop user-intent guard treats every way of running the wrapper as a run (OB-L38 round 3).

hooks/pretool-wrapper-userintent.py identifies the harness home's wrapper by path, by
file identity (a hard link elsewhere is the same file) and by content (a copy of a
non-trivial wrapper made in an earlier command), so the "resolves to a different
existing file" proof never passes such a file. It also refuses runs a reader-looking
command hides: `rg --pre` / `--hostname-bin` over or with the wrapper, sed's `e`
command and `s///e` flag when the command names the wrapper in any escaping, `less`
under a LESSOPEN/LESSCLOSE the command sets, xargs into a command that can run its
input, a for loop whose list expands to the wrapper and whose body runs the loop
variable, and a script or command word built at run time beside the harness home's
hooks/ or scripts/ directory. Harmless reads still pass and keep a live sentinel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-wrapper-userintent.py"
SID = "ob-l38-hidden"

WRAPPER_TEXT = ("#!/usr/bin/env bash\n# the harness home's /stop release wrapper (test copy)\n"
                "exec python3 \"$(dirname \"$0\")/../scripts/break-overnight-lock.py\" \"$@\"\n")
HELPER_TEXT = ("# the harness home's isolation release helper (test copy)\n"
               "import sys\nprint('released', sys.argv[1:])\n")


@pytest.fixture()
def env(tmp_path):
    home = tmp_path / "home"
    harness = home / ".claude"
    (harness / "hooks" / "tests").mkdir(parents=True)
    (harness / "scripts").mkdir(parents=True)
    wrapper = harness / "hooks" / "stop.sh"
    helper = harness / "scripts" / "break-overnight-lock.py"
    wrapper.write_text(WRAPPER_TEXT)
    helper.write_text(HELPER_TEXT)
    (harness / "hooks" / "other.sh").write_text("#!/usr/bin/env bash\necho other\n")
    (harness / "hooks" / "a.py").write_text("print('a')\n")
    for f in (wrapper, helper):
        f.chmod(0o755)
    project = tmp_path / "project"
    for rel in ("docs", "scripts", "hooks"):
        (project / rel).mkdir(parents=True)
    (project / "docs" / "a.md").write_text("hello\n")
    (project / "docs" / "notes.md").write_text("see the wrapper\n")
    # the project's own script of the same name, with its own content
    (project / "scripts" / "stop.sh").write_text("#!/usr/bin/env bash\necho project\n")
    (project / "scripts" / "stop.sh").chmod(0o755)
    linked = tmp_path / "linked"
    for rel in ("docs", "scripts", "hooks"):
        (linked / rel).mkdir(parents=True)
    os.link(wrapper, linked / "hooks" / "stop.sh")
    os.link(helper, linked / "scripts" / "break-overnight-lock.py")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "copy.sh").write_text(WRAPPER_TEXT)
    (scratch / "copy.sh").chmod(0o755)
    (scratch / "e.sed").write_text("1e bash ~/.claude/hooks/stop.sh\n")
    (scratch / "p.sed").write_text("s/a/b/\n/^$/d\n")
    state = tmp_path / "state"
    state.mkdir()
    return {"home": home, "harness": harness, "project": project, "linked": linked,
            "scratch": scratch, "state": state}


def _cwd(env, where):
    return {"P": env["project"], "L": env["linked"], "H": env["harness"],
            "HK": env["harness"] / "hooks"}[where]


def _run(env, command, where="P"):
    command = command.replace("{S}", str(env["scratch"])).replace("{H}", str(env["harness"]))
    cwd = str(_cwd(env, where))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID,
               "cwd": cwd}
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]),
                   CLAUDE_STATE_DIR=str(env["state"]),
                   CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


def _sentinel(env):
    return env["state"] / f"claude-stop-userintent-{SID}.flag"


W = "~/.claude/hooks/stop.sh"

# (1) a hard link to the wrapper under another path, and a copy made earlier
SAME_FILE = [
    ("bash hooks/stop.sh", "L"),
    ("./hooks/stop.sh", "L"),
    ("cd hooks && ./stop.sh", "L"),
    ("python3 scripts/break-overnight-lock.py", "L"),
    ("sh ./hooks/stop.sh --flag", "L"),
    ("bash {S}/copy.sh", "P"),
    ("{S}/copy.sh", "P"),
]

# (2) runs a reader-looking command hides
HIDDEN_RUNS = [
    (f"rg --pre bash x {W}", "P"),
    (f"rg --pre=bash x {W}", "P"),
    (f"rg -n x --pre=cat {W}", "P"),
    (f"rg --pre {W} x docs/", "P"),
    (f"rg --pre={W} x docs/", "P"),
    ("rg --pre=$HOME/.claude/hooks/stop.sh x docs/", "P"),
    ("rg --pre cat x ~/.claude/hooks/", "P"),
    ("rg --pre bash x ~/.claude/hooks/s*p.sh", "P"),
    ("rg --pre bash x", "HK"),
    (f"rg --hostname-bin {W} x docs/", "P"),
    ("rg --pre bash x hooks/stop.sh", "L"),
    ("sed 's/.*/bash ~\\/.claude\\/hooks\\/stop.sh/e' docs/a.md", "P"),
    ("sed 's|.*|bash ~/.claude/hooks/stop.sh|e' docs/a.md", "P"),
    ("sed -n 's#.*#bash ~/.claude/hooks/stop.sh#ep' docs/a.md", "P"),
    ("sed -n '1{s|.*|bash ~/.claude/hooks/stop.sh|;e}' docs/a.md", "P"),
    ("sed '1e bash ~/.claude/hooks/stop.sh' docs/a.md", "P"),
    ("sed -e '1e bash ~/.claude/hooks/st\\x6fp.sh' docs/a.md", "P"),
    ("sed 's/.*/bash ~\\/.claude\\/hooks\\/st\\o157p.sh/e' docs/a.md", "P"),
    ("sed --expression='s/.*/bash ~\\/.claude\\/hooks\\/stop.sh/e' docs/a.md", "P"),
    ("sed -E 's/(.*)/bash ~\\/.claude\\/hooks\\/stop.sh/e' docs/a.md", "P"),
    (f"sed e {W}", "P"),
    ("sed -f {S}/e.sed docs/a.md", "P"),
    (f"LESSOPEN='|bash %s' less {W}", "P"),
    (f"LESSOPEN=\"|bash %s\" less {W}", "P"),
    (f"export LESSOPEN='|bash %s'; less {W}", "P"),
    (f"env LESSOPEN='|bash %s' less {W}", "P"),
    (f"LESSCLOSE='bash %s %s' less {W}", "P"),
    ("LESSOPEN='|bash %s' less ~/.claude/hooks/s*p.sh", "P"),
    ("LESSOPEN='|bash %s' less hooks/stop.sh", "L"),
    (f"echo -exec bash {{}} \\; | xargs find {W}", "P"),
    ("echo -exec bash {} \\; | xargs find ~/.claude/hooks", "P"),
    ("ls ~/.claude/hooks/s*p.sh | xargs bash", "P"),
    ("ls ~/.claude/hooks/s*p.sh | xargs env bash", "P"),
    ("for f in ~/.claude/hooks/s*p.sh; do bash \"$f\"; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do \"$f\"; done", "P"),
    ("for f in s*p.sh; do bash $f; done", "HK"),
    ("for f in hooks/*.sh; do bash \"$f\"; done", "H"),
    ("for f in hooks/*.sh; do bash \"$f\"; done", "L"),
    ("for f in $(ls ~/.claude/hooks); do bash $f; done", "P"),
    ("bash $(ls | grep '^st.p')", "HK"),
    ("bash `ls | grep '^st.p'`", "HK"),
    ("bash $(ls ~/.claude/hooks/st*.sh)", "P"),
    ("bash $(ls hooks/st*.sh)", "H"),
    ("$(ls ~/.claude/hooks/st*.sh)", "P"),
    ("python3 $(ls ~/.claude/scripts/b*k.py)", "P"),
]


@pytest.mark.parametrize("command,where", SAME_FILE + HIDDEN_RUNS)
def test_a_hidden_run_is_refused_without_a_sentinel(env, command, where):
    proc = _run(env, command, where)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "USER-INTENT GUARD" in proc.stderr


@pytest.mark.parametrize("command,where", SAME_FILE)
def test_a_hard_link_run_consumes_the_sentinel(env, command, where):
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert not _sentinel(env).exists(), "a run of the wrapper's own file must consume the sentinel"


HARMLESS = [
    ("rg --pre-glob '*.pdf' x docs/", "P"),
    ("rg -n stop.sh --pre bash docs/", "P"),
    ("rg --pre=cat x docs/", "P"),
    ("rg -n 'stop.sh' ~/.claude/hooks/", "P"),
    ("sed -n '/stop.sh/p' ~/.claude/hooks/stop.sh", "P"),
    ("sed -n 1,20p ~/.claude/hooks/stop.sh", "P"),
    ("sed 's/e/E/g' docs/a.md", "P"),
    ("sed '/^#/d;s/exec/run/' ~/.claude/hooks/stop.sh", "P"),
    ("sed -e 's/x/y/' -e '/^$/d' ~/.claude/hooks/stop.sh", "P"),
    ("sed '1i\\# header' docs/a.md", "P"),
    ("sed -E 's/(stop)\\.sh/\\1.bash/g' docs/a.md", "P"),
    ("sed -n '/begin/,/end/{/x/p}' ~/.claude/hooks/stop.sh", "P"),
    ("sed -f {S}/p.sed ~/.claude/hooks/stop.sh", "P"),
    ("less ~/.claude/hooks/stop.sh", "P"),
    ("LESS=-R less ~/.claude/hooks/stop.sh", "P"),
    ("LESSOPEN='|cat %s' less docs/a.md", "P"),
    ("find hooks -name '*.sh' | xargs grep -n stop.sh", "P"),
    ("ls ~/.claude/hooks | xargs -n1 basename", "P"),
    ("find ~/.claude/hooks -name '*.py' | xargs python3 -m py_compile", "P"),
    ("find ~/.claude/hooks -name stop.sh | xargs wc -l", "P"),
    ("for f in ~/.claude/hooks/*.sh; do shellcheck \"$f\"; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do echo $f; done", "P"),
    ("for f in hooks/*.sh; do bash -n \"$f\"; done", "H"),
    ("for f in hooks/*.sh; do bash -n \"$f\"; done", "L"),
    ("for f in ~/.claude/hooks/*.py; do python3 -m py_compile \"$f\"; done", "P"),
    ("for f in docs/*.md; do bash \"$f\"; done", "P"),
    ("for f in a b c; do echo $f; done", "P"),
    ("$(which python3) -c 'print(1)'", "P"),
    ("$(which python3) -m pytest hooks/tests -q", "H"),
    ("ls $(echo st*)", "HK"),
    ("grep -n exit $(ls st*.sh)", "HK"),
    ("cat `ls stop.sh`", "HK"),
    ("cat hooks/stop.sh", "L"),
    ("bash -n hooks/stop.sh", "L"),
    ("bash scripts/stop.sh", "P"),
    ("./scripts/stop.sh", "P"),
]


@pytest.mark.parametrize("command,where", HARMLESS)
def test_a_harmless_command_passes_and_keeps_the_sentinel(env, command, where):
    assert _run(env, command, where).returncode == 0
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert _sentinel(env).exists(), "a harmless command consumed the single-use sentinel"


def test_after_stop_a_mention_then_a_hard_link_run_then_a_second_run(env):
    _sentinel(env).write_text("true")
    assert _run(env, "grep -rn stop.sh docs/", "L").returncode == 0
    assert _sentinel(env).exists()
    assert _run(env, "bash hooks/stop.sh", "L").returncode == 0
    assert not _sentinel(env).exists()
    assert _run(env, "bash hooks/stop.sh", "L").returncode == 2
