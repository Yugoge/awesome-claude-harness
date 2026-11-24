"""The harness keeps its own files on disk, under one state root (hooks/lib/harness_state_dir.py and .sh).

The incident behind it: the default control-state dir was /tmp, a memory-backed volume; with /tmp full the
orchestrator gate counted from zero, /do ran with no consent and /allow issued nothing. Pinned here:

  * the default root: <HOME>/.local/state/claude-harness/<harness home's name>-<crc32 of its real path>,
    the refusal record's own directory's parent; control state in its state/, logs in logs/, restart
    state in restart-state/; both twins agree; CLAUDE_STATE_DIR, when absolute, replaces state/ as before;
  * no file repeats the memory-backed default (the six former shell fallbacks, the command texts), and
    each former fallback now writes under the default root;
  * the inventory (lib/harness_temp_state.LOCATIONS) holds every name the code builds under the state dir;
  * protection follows: what refuses a write, move, overwrite or removal of control state refuses it at the
    default root as under an explicit state dir, and the refusal record's directory is refused too;
  * nothing moves what the previous version left in /tmp (test_no_automatic_move.py; the explicit carry-over
    is scripts/install/carry_state.py);
  * with /tmp full, every decision of the hooks that read or write control state is the one with /tmp free.

A full or replaced /tmp exists only inside a private mount namespace this test's own process starts
(as root, else a user namespace, else passwordless sudo, as on CI: hooks/tests/_private_ns.py); where none
can be made, those cases are skipped, and fail so on GitHub Actions. Nothing is written outside tmp_path.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import types
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
LIB = HOOKS / "lib"
sys.path.insert(0, str(LIB))
import harness_state_dir as hsd  # noqa: E402
import harness_temp_state as hts  # noqa: E402
sys.path.insert(0, str(HOOKS / "tests"))
import _private_ns  # noqa: E402

SID = "sid-state-root"
SH_LIB = LIB / "harness_state_dir.sh"


def expected_root(home: Path, harness: Path = ROOT) -> Path:
    """The layout's rule, computed here and not by the module under test."""
    real = os.path.realpath(harness)
    key = f"{real.rsplit(os.sep, 1)[-1].lstrip('.')}-{zlib.crc32(os.fsencode(real)):08x}"
    return home / ".local" / "state" / "claude-harness" / key


def env_for(home: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ANTHROPIC_"))}
    env.update(HOME=str(home), PYTHONDONTWRITEBYTECODE="1", CLAUDE_PYTHON_BIN=sys.executable, **extra)
    return env


def sh(script: str, env: dict, cwd=None) -> str:
    return subprocess.run(["bash", "-c", f'. "{SH_LIB}"; {script}'], env=env, text=True, capture_output=True,
                          check=True, cwd=cwd, timeout=60).stdout.strip()


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_STATE_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_RESTART_STATE_DIR", raising=False)
    return h


# ------------------------------------------------------------------------------------------- the root
def test_the_default_state_dir_is_on_disk_under_the_install_root(home):
    want = expected_root(home) / "state"
    assert hsd.state_root() == str(want.parent)
    assert hsd.harness_state_dir() == str(want) and want.is_dir()
    assert stat.S_IMODE(want.stat().st_mode) == 0o700
    assert sh("harness_state_root; harness_state_dir", env_for(home)).splitlines() == [str(want.parent), str(want)]
    import refusal_record
    assert Path(refusal_record.directory()).parent == want.parent  # one root, beside the refusal record


def test_the_root_follows_the_home_and_not_a_temp_or_runtime_dir(monkeypatch):
    # The fixture's home lies in pytest's temp, which may itself be on /tmp (as on CI), so the volume check is made
    # on a made-up home on disk; only resolved here, nothing is made. Temp and runtime variables point at the
    # memory-backed volumes to show that neither twin consults them.
    disk_home = "/var/lib/state-root-probe-home"
    lure = {"TMPDIR": "/tmp/lure", "TMP": "/dev/shm/lure", "TEMP": "/dev/shm/lure", "XDG_RUNTIME_DIR": "/run/user/1",
            "XDG_STATE_HOME": "/dev/shm/lure-state"}
    for k, v in {"HOME": disk_home, **lure}.items():
        monkeypatch.setenv(k, v)
    want = str(expected_root(Path(disk_home)))
    assert hsd.state_root() == want == sh("harness_state_root", env_for(Path(disk_home), **lure))
    for volume in ("/tmp", "/dev/shm", "/run"):
        assert not want.startswith(volume + "/")


@pytest.mark.parametrize("value", ["", "relative/state"])
def test_an_unusable_override_is_the_default(home, monkeypatch, value):
    monkeypatch.setenv("CLAUDE_STATE_DIR", value)
    want = str(expected_root(home) / "state")
    assert hsd.harness_state_dir() == want == sh("harness_state_dir", env_for(home, CLAUDE_STATE_DIR=value))


def test_an_absolute_override_is_used_as_before_and_nothing_is_made_or_moved(home, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "elsewhere") + "//")
    assert hsd.harness_state_dir() == str(tmp_path / "elsewhere")
    assert sh("harness_state_dir", env_for(home, CLAUDE_STATE_DIR=str(tmp_path / "elsewhere") + "//")) == str(
        tmp_path / "elsewhere")
    assert not (tmp_path / "elsewhere").exists() and not (home / ".local").exists()


def test_the_twins_agree_on_an_unusual_harness_home_name(tmp_path):
    odd = tmp_path / ".odd home é"
    (odd / "hooks" / "lib").mkdir(parents=True)
    shutil.copy2(SH_LIB, odd / "hooks" / "lib")
    out = subprocess.run(["bash", "-c", '. "$1"; harness_state_root', "_", str(odd / "hooks/lib/harness_state_dir.sh")],
                         env=env_for(tmp_path), text=True, capture_output=True, check=True).stdout.strip()
    assert out == str(expected_root(tmp_path, odd)) == hsd.state_root(home=str(tmp_path), harness=str(odd))


def test_logs_and_restart_state_live_under_the_state_root(home):
    root = expected_root(home)
    import score_log
    import subagent_restart
    assert score_log.log_path() == root / "logs" / "lifecycle.jsonl"
    assert subagent_restart.state_dir() == root / "restart-state"
    env = env_for(home)
    assert sh(f'. "{LIB / "checkpoint-core.sh"}" >/dev/null 2>&1; printf %s "$CHECKPOINT_LOG_DIR"', env) == str(
        root / "logs")
    fswatch = (HOOKS / "git-fswatch.sh").read_text()
    lines = [ln for ln in fswatch.splitlines() if ln.startswith(("LOG_FILE=", "LOCK_FILE="))]
    assert sh("USER=u; REPO_NAME=r; " + "; ".join(lines) + '; printf "%s\\n%s" "$LOG_FILE" "$LOCK_FILE"', env) \
        .splitlines() == [str(root / "logs" / "git-fswatch-r.log"), str(root / "state" / "git-fswatch-u-r.lock")]
    reader = subprocess.run(["bash", str(HOOKS / "fswatch-manager.sh"), "logs", "/x"], env=env, text=True,
                            capture_output=True, timeout=60).stdout
    assert f"{root / 'logs'}/git-fswatch-" in reader  # the log reader looks where the watcher writes


# --------------------------------------------------------------------------------- the old default
def _sources(*globs):
    out = []
    for g in globs:
        out += [p for p in ROOT.glob(g) if p.is_file() and "/tests/" not in p.as_posix()]
    return sorted(set(out))


def test_no_file_repeats_the_memory_backed_default():
    defs, texts = [], []
    for path in _sources("hooks/**/*.sh", "hooks/**/*.py", "hooks/*", "scripts/**/*.sh", "scripts/*", "commands/*.md"):
        text = path.read_text(errors="ignore")
        if path != SH_LIB and "harness_state_dir() {" in text:
            defs.append(str(path.relative_to(ROOT)))
        if "else `/tmp`" in text or "default /tmp)" in text:
            texts.append(str(path.relative_to(ROOT)))
    assert defs == [] and texts == [], (defs, texts)
    assert '"/tmp"' not in (LIB / "harness_state_dir.py").read_text()


@pytest.mark.parametrize("hook", ["lib/checkpoint-core.sh", "git-fswatch.sh", "pretool-worktree-guard.sh",
                                  "push.sh", "userprompt-consent-allowlist.sh", "userprompt-tmpfs-pressure.sh"])
def test_each_former_fallback_sources_the_one_resolver(hook):
    text = (HOOKS / hook).read_text()
    assert "lib/harness_state_dir.sh" in text or "/harness_state_dir.sh" in text
    assert "printf '%s\\n' /tmp" not in text


def test_the_worktree_guard_and_the_allow_hook_write_under_the_default_root(home, tmp_path):
    state = expected_root(home) / "state"
    env = env_for(home, CLAUDE_PROJECT_DIR=str(tmp_path))
    payload = {"tool_name": "Bash", "tool_input": {"command": "true"}, "session_id": SID, "cwd": str(tmp_path),
               "hook_event_name": "PreToolUse"}
    git = dict(env, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path / "repo")], env=git, check=True)
    subprocess.run(["git", "-C", str(tmp_path / "repo"), "commit", "-q", "--allow-empty", "-m", "base"], env=git,
                   check=True)  # the guard looks only where a main branch exists
    subprocess.run(["bash", str(HOOKS / "pretool-worktree-guard.sh")], input=json.dumps(payload), env=env,
                   text=True, capture_output=True, cwd=tmp_path / "repo", timeout=60)
    assert (state / "worktree-guard-cache").exists()
    prompt = {"prompt": "/allow Bash", "session_id": SID, "hook_event_name": "UserPromptSubmit"}
    out = subprocess.run(["bash", str(HOOKS / "userprompt-consent-allowlist.sh")], input=json.dumps(prompt),
                         env=env, text=True, capture_output=True, timeout=60)
    assert "Grant recorded" in out.stdout + out.stderr, out.stderr
    assert json.loads((state / "claude-grants" / f"{SID}.json").read_text())["session_id"] == SID


# --------------------------------------------------------------------------------------- inventory
_NAME = r"([A-Za-z0-9_.{}*\-/$\[\]<>]+)"
_SCANS = [
    rf"harness_state_dir\(\)\}}?/{_NAME}",                                       # f"{harness_state_dir()}/x"
    r"(?<![\w.])(?:harness_state_dir|state_dir|state_root)\(\)\s*\+\s*f?['\"]/([^'\"]+)['\"]",
    r"(?:join|Path)\(\s*(?:harness_state_dir|state_dir|state_root)\(\)\s*,\s*[fr]?['\"]([^'\"]+)['\"]",
    r"(?:join|Path)\(\s*state\s*,\s*[fr]?['\"]([^'\"]+)['\"]",                  # tool-policy's `state`
    rf"\$\(harness_state_dir\)/{_NAME}",
]
# Files whose state_dir() or `state` is another directory (the restart, capability, attribution and
# send roots): their names are not the hook state dir's.
_OTHER_STATE = {"hooks/lib/subagent_restart.py", "hooks/lib/attribution_journal.py", "hooks/lib/send_policy.py",
                "hooks/capability-canary.py", "hooks/lib/capability_state.py"}


def scanned_state_names() -> dict:
    import re
    found: dict = {}
    for path in _sources("hooks/**/*.py", "hooks/**/*.sh", "scripts/**/*.py", "scripts/**/*.sh", "scripts/*"):
        rel = str(path.relative_to(ROOT))
        if rel in _OTHER_STATE or path.name.startswith("harness_"):
            continue
        text = path.read_text(errors="ignore")
        for rx in _SCANS:
            for m in re.finditer(rx, text):
                name = re.sub(r"\{[^}]*\}|\$\{?\w+\}?|\[[^\]]*\]|<[^>]*>|\*", "x", m.group(1)).strip("/")
                if name.strip("x"):  # placeholders only (a name built of constants) names nothing here
                    found.setdefault(name, set()).add(rel)
    return found


def test_every_name_the_code_builds_under_the_state_dir_is_inventoried(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path))
    names = scanned_state_names()
    missing = {n: sorted(f) for n, f in names.items()
               if (hts.classify(str(tmp_path / n)) or types.SimpleNamespace(kind=None)).kind != hts.CONTROL}
    assert missing == {}
    # the scan is not vacuous: it sees the four entries the inventory missed before
    seen = " ".join(names)
    for stem in ("claude-tool-ran-", ".checkpoint-overtime-", "codex-unavailable.json", "report-provenance"):
        assert stem in seen, stem


def test_each_inventoried_state_dir_entry_is_moved_and_documented():
    doc = (ROOT / "docs" / "reference" / "harness-temp-state.md").read_text()
    for loc in hts.LOCATIONS:
        assert f"| {loc.name} |" in doc, loc.name
        if loc.kind == hts.CONTROL and loc.name not in hts.NOT_IN_STATE_DIR:
            assert all(hts.moved_by_default(p[0].replace("*", "x")) for p in loc.patterns if len(p) == 1), loc.name
    for foreign in ("notes.txt", "claude-0", "claude-scratch", "codex-outputs", "systemd-private-x", ".X11-unix"):
        assert not hts.moved_by_default(foreign), foreign


# -------------------------------------------------------------------------------------- protection
def _decide(home: Path, tool: str, tool_input: dict, state=None, agent=None, cwd=None) -> int:
    """Exit 2 when any registered PreToolUse hook that judges writes refuses the call."""
    payload = {"tool_name": tool, "tool_input": tool_input, "session_id": SID, "hook_event_name": "PreToolUse",
               "cwd": str(cwd or home.parent / "proj"), "transcript_path": str(home / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5f6a7b8", agent_type=agent, subagent_type=agent)
    proj = cwd or home.parent / "proj"  # a project apart from HOME, as a product checkout is
    proj.mkdir(exist_ok=True)
    env = env_for(home, CLAUDE_PROJECT_DIR=str(proj), **({"CLAUDE_STATE_DIR": str(state)} if state else {}))
    hooks = [[sys.executable, str(HOOKS / "pretool-tool-policy.py")], [sys.executable, str(HOOKS / "pretool-write-gate.py")]]
    if tool == "Bash":
        hooks.append(["bash", str(HOOKS / "pretool-bash-safety.sh")])
    runs = [subprocess.run(h, input=json.dumps(payload), env=env, text=True, capture_output=True, timeout=120,
                           cwd=str(proj)) for h in hooks]
    _decide.said = " || ".join(r.stderr.strip()[:200] for r in runs if r.returncode)
    return 2 if any(r.returncode == 2 for r in runs) else 0


def _forms(path: str) -> list:
    return [("Write", {"file_path": path, "content": "true"}),
            ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}),
            ("Bash", {"command": f"echo true > {path}"}),
            ("Bash", {"command": f"printf true | tee {path}"}),
            ("Bash", {"command": f"cp /etc/hostname {path}"}),
            ("Bash", {"command": f"mv {path} {path}.x"}),
            ("Bash", {"command": f"rm -f {path}"}),
            ("Bash", {"command": f"ln -sf /etc/hostname {path}"}),
            ("Bash", {"command": f"python3 -c \"open('{path}', 'w').write('true')\""})]


ENTRIES = [f"claude-orchestrator-consent-{SID}.flag", f"claude-grants/{SID}.json", f"claude-commit-userintent-{SID}.flag",
           f"claude-do-task-{SID}.json", "agentic-commit/push/0123456789abcdef/0123456789abcdef/main.json",
           f"claude-bulk-commit-sentinel-{SID}-n.json"]


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("agent", [None, "dev"])
def test_protection_at_the_default_root_is_the_protection_under_an_explicit_state_dir(tmp_path, home, entry, agent):
    """Each form's decision for a control entry at the default root (CLAUDE_STATE_DIR unset) is its decision
    for the same entry under an explicit state dir: what refuses it there refuses it at the new root."""
    default, explicit = expected_root(home) / "state", tmp_path / "explicit"
    for d in (default, explicit):
        (d / entry).parent.mkdir(parents=True, exist_ok=True)
        (d / entry).write_text("a")  # existing, so Edit, mv and rm have a target
    for tool, ti in _forms(str(default / entry)):
        at_default, said = _decide(home, tool, ti, agent=agent), _decide.said
        ti_explicit = json.loads(json.dumps(ti).replace(str(default), str(explicit)))
        assert at_default == _decide(home, tool, ti_explicit, state=explicit, agent=agent), (tool, said, _decide.said)
        # No forged grant, consent, intent mark, sidecar or token through a file tool or a shell write the hooks
        # read (interpreter code they read only for the consent and intent marks, see the report's limits).
        if not ti.get("command", "").startswith("python3") and (agent or entry != ENTRIES[-1]):
            assert at_default == 2, (tool, said)


@pytest.mark.parametrize("agent", [None, "dev"])
def test_the_refusal_record_directory_is_refused_to_every_agent(home, agent):
    import refusal_record
    folder = Path(refusal_record.directory())
    folder.mkdir(parents=True)
    (folder / "refusals-2026-01-01.jsonl").write_text("{}\n")
    for tool, ti in _forms(str(folder / "refusals-2026-01-01.jsonl"))[:-1] + [
            ("Bash", {"command": f"rm -rf {expected_root(home)}"}), ("Bash", {"command": f"mv {folder} /var/x"})]:
        assert _decide(home, tool, ti, agent=agent) == 2, (tool, ti)
    assert _decide(home, "Bash", {"command": f"cat {folder}/refusals-2026-01-01.jsonl"}, agent=agent) == 0


# ------------------------------------------------------------------------------- a full system temp
def in_private_tmp(script: str, env: dict, full: bool, keep: Path) -> subprocess.CompletedProcess:
    """Run bash `script` in a private mount namespace whose /tmp is a fresh 64 KiB tmpfs, filled to its last
    block when `full`. The test's own directory `keep` stays what it was wherever pytest's temp lies: when it
    lies under /tmp (CI's runner), it is bound back at its own path before the fill, from a descriptor
    opened before the mount, so the scenario's home, work and temp dirs are never on the replaced volume."""
    fill = 'head -c 1048576 /dev/zero > /tmp/.fill 2>/dev/null; while : > "/tmp/.f$RANDOM" 2>/dev/null; do :; done'
    pre = ('exec 3<"$1"; mount -t tmpfs -o size=64k,nr_inodes=64 none /tmp || exit 97; '
           'case "$1/" in /tmp/*) { mkdir -p "$1" && mount -c --bind /proc/self/fd/3 "$1"; } || exit 97;; esac; '
           f'exec 3<&-; {fill if full else ":"}; set --; ')
    way = _private_ns.require("the full-system-temp case")  # root, else a user namespace, else sudo (CI)
    return subprocess.run(_private_ns.unshare_argv(way, env, ["bash", "-c", pre + script, "_", os.path.realpath(keep)]),
                          text=True, capture_output=True, timeout=600)


SCENARIO = r'''
cd "$WORK" || exit 97  # the scenario's own dirs are what it judges in: never run elsewhere
gate() {  # one main-agent Bash call through the orchestrator gate, then its PostToolUse record
  local id="toolu_$1" p
  p="{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"touch f$1\"},\"session_id\":\"$SID\",\"tool_use_id\":\"$id\",\"hook_event_name\":\"PreToolUse\",\"cwd\":\"$WORK\"}"
  printf '%s' "$p" | "$PY" "$HOOKS/pretool-orchestrator-gate.py" >/dev/null 2>&1; echo "gate$1=$?"
  printf '%s' "${p/PreToolUse/PostToolUse}" | "$PY" "$HOOKS/posttool-orchestrator-ran.py" >/dev/null 2>&1
}
for i in 1 2 3 4 5 6 7 8; do gate $i; done
out=$(printf '{"prompt":"/do run the probe","session_id":"%s","hook_event_name":"UserPromptSubmit","cwd":"%s"}' "$SID2" "$WORK" \
  | "$PY" "$HOOKS/userprompt-launch.py" 2>&1)
case "$out" in *"Consent granted"*) echo do-consent=granted ;; *) echo do-consent=none ;; esac
printf '%s' "{\"session_id\":\"$SID2\"}" | "$PY" -c 'import sys, json; sys.path.insert(0, sys.argv[1]); from lib import allowlist; print("has-consent=%s" % allowlist.has_do_consent(json.load(sys.stdin)))' "$HOOKS"
out=$(printf '{"prompt":"/allow Bash","session_id":"%s","hook_event_name":"UserPromptSubmit"}' "$SID3" \
  | bash "$HOOKS/userprompt-consent-allowlist.sh" 2>&1)
case "$out" in *"Grant recorded"*) echo allow=granted ;; *) echo allow=none ;; esac
'''


def run_scenario(harness: Path, work: Path, full: bool) -> list:
    home = work / "home"
    home.mkdir(parents=True)
    (work / "wd").mkdir()
    env = env_for(home, WORK=str(work / "wd"), HOOKS=str(harness / "hooks"), PY=sys.executable, SID="sid-full-1",
                  SID2="sid-full-2", SID3="sid-full-3", TMPDIR=str(work / "t"))
    (work / "t").mkdir()
    proc = in_private_tmp(SCENARIO, env, full, keep=work)
    assert proc.returncode != 97, proc.stderr
    return [ln for ln in proc.stdout.splitlines() if "=" in ln]


def test_every_decision_is_the_same_with_the_system_temp_full(tmp_path):
    free = run_scenario(ROOT, tmp_path / "free", full=False)
    full = run_scenario(ROOT, tmp_path / "full", full=True)
    assert free == full
    assert free == [f"gate{i}={0 if i <= 5 else 2}" for i in range(1, 9)] + [
        "do-consent=granted", "has-consent=True", "allow=granted"], free
