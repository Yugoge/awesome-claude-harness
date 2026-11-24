"""When a volume a session needs runs short of space, the harness says so and clears what is provably dead.

hooks/userprompt-tmpfs-pressure.sh (and hooks/session-tmpfs-banner.sh, which runs it at SessionStart) and the
periodic scripts/install/tmp-cleanup-install.sh share one reaction: the program's --pressure mode. Every case
runs inside a private mount namespace that only this test's process tree sees: /tmp and /var/tmp are small
private tmpfs mounts there, and the watched volume is a small tmpfs over a directory of the test's own, so
nothing of the host is listed, filled or removed. The test's own place, /tmp/f, is a tmpfs of the namespace too,
so the cases do not depend on where pytest's temp or the tree lie. As root the namespace is made directly, else
as an unprivileged user namespace, else through passwordless sudo (CI's runner, whose kernel refuses the second).
Where none of the three works the cases skip with that reason and a warning; on GitHub Actions they fail instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _private_ns  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "userprompt-tmpfs-pressure.sh"
PROGRAM = ROOT / "scripts" / "install" / "tmp-cleanup-install.sh"

# Inside the namespace: the private /tmp and /var/tmp, the test's own tmpfs at /tmp/f (the tree read-only at
# /tmp/f/repo), the watched volume V at
# /tmp/f/vol (2 MiB), the session root, state root and CLI command output root on it, a live process L (its
# start time in the owner mark) and a dead pid D.
SETUP = r"""
set -u
REPO="$1"; VOLSIZE="$2"
# The tree may lie under /tmp or /var/tmp, which the mounts below cover: it is reached from the working directory
# (a hidden path still names it there; -c keeps mount from resolving "." to that path) by a read-only bind.
cd "$REPO" && mount -t tmpfs -o size=1m none /tmp && mount -t tmpfs -o size=1m none /var/tmp \
  && mkdir /tmp/f && mount -t tmpfs -o size=16m none /tmp/f && mkdir /tmp/f/repo /tmp/f/vol \
  && mount -c --rbind . /tmp/f/repo && mount -o remount,bind,ro /tmp/f/repo \
  && mount -t tmpfs -o size="$VOLSIZE" none /tmp/f/vol && cd / || exit 99
F=/tmp/f; V=$F/vol; REPO=$F/repo
[ -f "$REPO/hooks/userprompt-tmpfs-pressure.sh" ] || { echo "the tree is not reachable at $REPO" >&2; exit 98; }
export HOME=$F/home CLAUDE_STATE_DIR=$V/state TMPDIR=$V/scratch CLAUDE_CODE_TMPDIR=$V/cli CLAUDE_HOME=$F/home
unset CLAUDE_PROJECT_DIR
mkdir -p "$HOME" "$CLAUDE_STATE_DIR" "$TMPDIR"
read -r BOOT < /proc/sys/kernel/random/boot_id
owner() {  # <dir> <sid> <pid>: the owner mark hooks/session-scratch-init.sh writes
  local st=""; mkdir -p "$1"
  [ -r "/proc/$3/stat" ] && st=$(sed -E 's/^[0-9]+ \(.*\) //' "/proc/$3/stat" | awk '{print $20}')
  printf '{"sid": "%s", "pid": "%s", "pid_start_time": "%s", "boot_id": "%s", "created_at": "t"}' \
    "$2" "$3" "$st" "$BOOT" > "$1/.owner"
}
sleep 300 & L=$!
bash -c 'exit 0' & D=$!; wait "$D"
PIDS="$L"; trap 'kill $PIDS 2>/dev/null' EXIT
prompt() { printf '{"session_id": "s-cur"}' | bash "$REPO/hooks/userprompt-tmpfs-pressure.sh"; }
fill() { dd if=/dev/zero of="$V/fill" bs=4k 2>/dev/null; true; }
"""

# A dead session (root, command output, control state), a live one, a dead one whose dispatch temp directory a live
# process works in, a directory whose owner mark names another session, and a large foreign file.
FIXTURES = r"""
owner "$TMPDIR/s-dead" s-dead "$D"; echo x > "$TMPDIR/s-dead/work.txt"
owner "$TMPDIR/s-live" s-live "$L"; echo x > "$TMPDIR/s-live/work.txt"
mkdir "$TMPDIR/s-live/dispatch-old" "$TMPDIR/s-live/dispatch-used" "$TMPDIR/s-live/dispatch-open"
printf '%s\n{"open": ["t1"], "kept": ["%s", "%s"], "held": []}\n' "$TMPDIR/s-live/dispatch-open" \
  "$TMPDIR/s-live/dispatch-old" "$TMPDIR/s-live/dispatch-used" > "$TMPDIR/s-live/.dispatch-tmp"
(cd "$TMPDIR/s-live/dispatch-used" && exec sleep 300) & PIDS="$PIDS $!"
owner "$TMPDIR/s-busy" s-busy "$D"; mkdir -p "$TMPDIR/s-busy/dispatch-1"
(cd "$TMPDIR/s-busy/dispatch-1" && exec sleep 300) & PIDS="$PIDS $!"
owner "$TMPDIR/s-other" s-someone-else "$D"
head -c 1700000 /dev/zero > "$TMPDIR/foreign-big.bin"
for s in s-dead s-live; do
  mkdir -p "$CLAUDE_CODE_TMPDIR/claude-0/-proj/$s/tasks"
  echo out > "$CLAUDE_CODE_TMPDIR/claude-0/-proj/$s/tasks/b1.output"
  touch -d '-1 hour' "$CLAUDE_CODE_TMPDIR/claude-0/-proj/$s/tasks/b1.output"
  echo 0 > "$CLAUDE_STATE_DIR/claude-tool-streak-$s.json"
done
sleep 0.2
"""

STATE = r"""
for p in s-dead s-dead/.owner s-dead/work.txt s-live s-live/dispatch-old s-live/dispatch-used s-live/dispatch-open s-busy/dispatch-1 s-other \
         foreign-big.bin; do [ -e "$TMPDIR/$p" ] && echo "kept $p" || echo "gone $p"; done
for s in s-dead s-live; do
  [ -e "$CLAUDE_CODE_TMPDIR/claude-0/-proj/$s/tasks/b1.output" ] && echo "kept output $s" || echo "gone output $s"
  [ -e "$CLAUDE_STATE_DIR/claude-tool-streak-$s.json" ] && echo "kept state $s" || echo "gone state $s"
done
"""


def _ns(body: str, volsize: str = "2m", timeout: int = 120):
    way = _private_ns.require("the space-pressure cases")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GIT_"))}
    p = subprocess.run(_private_ns.unshare_argv(way, env, ["bash", "-c", SETUP + body, "_", str(ROOT), volsize]),
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode == 99:  # a namespace can be made here (above), so a setup that fails is a defect, not a skip
        pytest.fail(f"the case's namespace setup failed where a namespace can be made: {p.stderr.strip()[:300]}")
    return p


def test_a_full_volume_with_an_unwritable_counter_still_gets_the_notice():
    p = _ns('fill\necho "== 1"; prompt\necho "== 2"; prompt\n')
    first, second = p.stdout.split("== 2")
    for text in (first, second):  # the counter cannot be written, so the notice repeats and says why
        assert "[space] SHORT: /tmp/f/vol" in text, p.stdout + p.stderr
        assert "could not record" in text, p.stdout


def test_the_notice_prints_once_per_change_of_state():
    p = _ns(FIXTURES + 'echo "== 1"; prompt\necho "== 2"; prompt\nrm -f "$TMPDIR/foreign-big.bin"\n'
                      'echo "== 3"; prompt\n')
    one, rest = p.stdout.split("== 2")
    two, three = rest.split("== 3")
    assert "[space] SHORT: /tmp/f/vol" in one and "could not record" not in one, p.stdout + p.stderr
    assert "/tmp/f/vol" not in two, p.stdout
    assert "[space] OK: /tmp/f/vol" in three and "SHORT: /tmp/f/vol" not in three, p.stdout


def test_the_prompt_reaction_removes_only_what_is_provably_dead_and_names_the_rest():
    p = _ns(FIXTURES + "prompt > $F/notice\n" + STATE + 'cat "$F/notice"\n')
    out = p.stdout
    assert "gone s-dead/work.txt" in out and "gone output s-dead" in out, out + p.stderr
    assert "gone s-live/dispatch-old" in out, out  # retired by its session and unused
    for kept in ("kept s-dead/.owner", "kept state s-dead", "kept s-live","kept s-live/dispatch-used", "kept s-live/dispatch-open", "kept s-busy/dispatch-1", "kept s-other", "kept foreign-big.bin",
                 "kept output s-live", "kept state s-live"):
        assert kept in out, out
    assert "foreign-big.bin" in out.split("[space] largest", 1)[1], out  # what it cannot remove it names
    assert "[space] removed" in out, out


def test_nothing_is_removed_while_no_watched_volume_is_short():
    p = _ns(FIXTURES.replace("1700000", "1000") + "prompt > $F/notice\n" + STATE, volsize="64m")
    assert "kept s-dead" in p.stdout and "kept output s-dead" in p.stdout, p.stdout + p.stderr


def test_the_banner_is_the_same_notice_at_session_start():
    p = _ns('fill\nprintf \'{"session_id": "s-cur"}\' | bash "$REPO/hooks/session-tmpfs-banner.sh"\n')
    assert "[space] SHORT: /tmp/f/vol" in p.stdout, p.stdout + p.stderr


def test_the_periodic_program_reacts_the_same_way_and_keeps_its_age_rules():
    body = FIXTURES + r"""
touch -d '-3 days' /tmp/codex-output-old; touch /tmp/codex-output-new
bash "$REPO/scripts/install/tmp-cleanup-install.sh" --dry-run > "$F/dry"
""" + STATE + r"""
echo "== real"
bash "$REPO/scripts/install/tmp-cleanup-install.sh"
""" + STATE + r"""
for f in codex-output-old codex-output-new; do [ -e /tmp/$f ] && echo "kept $f" || echo "gone $f"; done
echo "== dry"; cat "$F/dry"
"""
    p = _ns(body)
    listed, rest = p.stdout.split("== real")
    after, dry = rest.split("== dry")
    assert "gone" not in listed, p.stdout + p.stderr  # a dry run lists and removes nothing
    listed_dead = [line.split(": ", 1)[1] for line in dry.splitlines() if line.startswith("short space, dead: ")]
    assert sorted(listed_dead) == ["/tmp/f/vol/cli/claude-0/-proj/s-dead/tasks/b1.output",
                                   "/tmp/f/vol/scratch/s-dead/work.txt", "/tmp/f/vol/scratch/s-live/dispatch-old"], dry
    assert "gone s-dead/work.txt" in after and "kept s-live" in after and "kept s-busy/dispatch-1" in after, after
    assert "kept s-dead/.owner" in after and "kept state s-dead" in after, after
    assert "gone s-live/dispatch-old" in after and "kept s-live/dispatch-used" in after, after
    assert "kept foreign-big.bin" in after and "kept s-other" in after, after
    assert "gone codex-output-old" in after and "kept codex-output-new" in after, after


def test_the_check_at_a_prompt_is_cheap():
    """Work per prompt: no volume short; short with 300 live session roots and nothing to remove. The work is
    counted as the processes a prompt starts (in a PID namespace of its own, whose last PID is that count), not
    timed: a count is the same on a slow or busy machine (C9). The hook runs from a copy on a tmpfs of its own
    (H), so the harness home, a watched volume, is not the disk the tree lies on, however full that is."""
    body = r"""
H=$F/h; mkdir "$H" && mount -t tmpfs -o size=32m none "$H" && mkdir "$H/hooks" "$H/scripts" \
  && cp -r "$REPO/hooks/lib" "$REPO/hooks/userprompt-tmpfs-pressure.sh" "$H/hooks/" \
  && cp -r "$REPO/scripts/install" "$H/scripts/" || exit 97
for i in $(seq 300); do owner "$TMPDIR/live-$i" "live-$i" "$L"; done
t() {  # <name>: one prompt, then the processes it started
  local n
  n=$(unshare -pf bash -c 'printf "{\"session_id\": \"s-cur\"}" | bash "$1/hooks/userprompt-tmpfs-pressure.sh" \
        > /dev/null; read -r n < /proc/sys/kernel/ns_last_pid; echo "$n"' _ "$H") && echo "$1 $n"
}
t calm; t calm
head -c 500000 /dev/zero > "$TMPDIR/foreign-big.bin"  # short (under a quarter free), the counter still written
t short-first; t short; t short
"""
    p = _ns(body, volsize="2m")
    n = {}
    for line in p.stdout.splitlines():
        name, _, value = line.partition(" ")
        if value.isdigit():
            n[name] = max(n.get(name, 0), int(value))
    print("prompt cost (processes):", n)
    assert set(n) == {"calm", "short-first", "short"}, p.stdout + p.stderr
    # Calm and a short volume within a minute of the last reaction: a fixed few processes. The first reaction
    # with 300 live session roots: about one per root, and it is that reaction (more than the short prompts after).
    assert n["calm"] < 60 and n["short"] < 90 and n["short"] < n["short-first"] < 700, n


# A session root with role directories (agents' own <role>/<agent id>/ and the role's drafts): <name>:<hours untouched>.
ROLES = r"""
roles() {  # <session dir> <name:hours>...
  local d=$1 r n h; shift
  for r in "$@"; do n=${r%%:*}; h=${r##*:}; mkdir -p "$d/$n/a1f$h"; echo d > "$d/$n/draft.md"; echo s > "$d/$n/a1f$h/notes"
    find "$d/$n" -exec touch -d "-$h hours" {} +; done
}
there() { for p in "$@"; do [ -e "$TMPDIR/$p" ] && echo "kept $p" || echo "gone $p"; done; }
"""


def test_pressure_keeps_a_dead_sessions_young_role_directories_and_removes_old_ones_oldest_first():
    body = ROLES + r"""
owner "$TMPDIR/s-roles" s-roles "$D"; echo x > "$TMPDIR/s-roles/work.txt"
roles "$TMPDIR/s-roles" ba:30 qa:48 pm:1
head -c 1700000 /dev/zero > "$TMPDIR/foreign-big.bin"
bash "$REPO/scripts/install/tmp-cleanup-install.sh" --dry-run > "$F/dry"
prompt > /dev/null
there s-roles s-roles/.owner s-roles/work.txt s-roles/qa s-roles/ba s-roles/pm
echo "== dry"; cat "$F/dry"
"""
    p = _ns(body)
    after, dry = p.stdout.split("== dry")
    for line in ("kept s-roles", "kept s-roles/.owner", "gone s-roles/work.txt", "gone s-roles/qa", "gone s-roles/ba",
                 "kept s-roles/pm"):
        assert line in after, p.stdout + p.stderr
    order = [line.rsplit("/", 1)[1] for line in dry.splitlines() if line.startswith("short space, untouched 24h: ")]
    assert order == ["qa", "ba"], dry


def test_the_age_rule_takes_whole_directories():
    body = ROLES + r"""
owner "$TMPDIR/s-old" s-old "$D"; roles "$TMPDIR/s-old" qa:200 ba:50
echo x > "$TMPDIR/s-old/old.txt"; touch -d '-100 hours' "$TMPDIR/s-old/old.txt"; echo x > "$TMPDIR/s-old/new.txt"
owner "$TMPDIR/s-alive" s-alive "$L"; roles "$TMPDIR/s-alive" qa:200
echo x > "$TMPDIR/s-alive/top.txt"; touch -d '-100 hours' "$TMPDIR/s-alive/top.txt"
owner "$TMPDIR/s-empty" s-empty "$D"; touch -d '-100 hours' "$TMPDIR/s-empty/.owner"
bash "$REPO/scripts/install/tmp-cleanup-install.sh"
there s-old/qa s-old/ba s-old/old.txt s-old/new.txt s-alive/qa s-alive/top.txt s-empty
"""
    p = _ns(body, volsize="64m")
    for line in ("gone s-old/qa", "kept s-old/ba", "gone s-old/old.txt", "kept s-old/new.txt", "gone s-alive/qa",
                 "kept s-alive/top.txt", "gone s-empty"):
        assert line in p.stdout, p.stdout + p.stderr


# Whether the process that owned a session is gone: hooks/lib/dispatch_temp.py owner_state, for the reaction and the
# dispatch temp alike. s-held: a dead-owner session whose agent went on in the background (a held dispatch dir).
HELD = r"""
owner "$TMPDIR/s-held" s-held "$D"; mkdir "$TMPDIR/s-held/dispatch-bg"
printf '\n{"open": [], "kept": [], "held": ["%s"]}\n' "$TMPDIR/s-held/dispatch-bg" > "$TMPDIR/s-held/.dispatch-tmp"
start_held() { python3 "$REPO/hooks/lib/dispatch_temp.py" --start "$TMPDIR/s-held" s-held; there s-held/dispatch-bg; }
there() { for p in "$@"; do [ -e "$TMPDIR/$p" ] && echo "kept $p" || echo "gone $p"; done; }
"""
CANNOT_TELL = ("kept s-dead/work.txt", "kept output s-dead", "kept s-live/dispatch-old", "kept s-held/dispatch-bg")


def test_without_proc_nothing_is_judged_dead_or_unused():
    """No /proc mounted (an empty /proc, as on a system without it; df keeps its mount table)."""
    body = FIXTURES + HELD + r"""
cp /proc/self/mountinfo "$F/mi"; cp /proc/self/mounts "$F/mo"
mount -t tmpfs none /proc || exit 99
mkdir /proc/self && cp "$F/mi" /proc/self/mountinfo && cp "$F/mo" /proc/self/mounts
prompt > "$F/notice"; start_held
""" + STATE + 'cat "$F/notice"\n'
    p = _ns(body)
    for line in CANNOT_TELL:
        assert line in p.stdout, p.stdout + p.stderr
    assert "[space] SHORT: /tmp/f/vol" in p.stdout and "[space] could not judge" in p.stdout, p.stdout


def test_without_a_process_id_nothing_is_judged_dead():
    """An owner mark that names no process (a CLI that gives hooks none): no pid, or an empty one."""
    body = FIXTURES + HELD + r"""
for s in s-dead s-held; do sed -i 's/"pid": "[0-9]*"/"pid": ""/' "$TMPDIR/$s/.owner"; done
mkdir -p "$TMPDIR/s-nopid"; printf '{"sid": "s-nopid", "created_at": "t"}' > "$TMPDIR/s-nopid/.owner"
echo x > "$TMPDIR/s-nopid/work.txt"
prompt > "$F/notice"; start_held; there s-nopid/work.txt
""" + STATE + 'cat "$F/notice"\n'
    p = _ns(body)
    for line in CANNOT_TELL[:2] + CANNOT_TELL[3:] + ("kept s-nopid/work.txt",):
        assert line in p.stdout, p.stdout + p.stderr
    assert "[space] could not judge" in p.stdout, p.stdout


# The control state of a session whose command (/do) is open: its task record, consent and commit grant in the state
# dir, and its dispatch temp state in its root.
CONTROL_STATE = r"""
for s in s-dead s-live; do
  for n in claude-do-task-$s.json claude-orchestrator-consent-$s.flag claude-commit-grant-$s.json; do
    echo '{}' > "$CLAUDE_STATE_DIR/$n"; done
done
printf '\n{"open": [], "kept": [], "held": []}\n' > "$TMPDIR/s-dead/.dispatch-tmp"
control() { for s in s-dead s-live; do for n in claude-do-task-$s.json claude-orchestrator-consent-$s.flag \
  claude-commit-grant-$s.json; do [ -e "$CLAUDE_STATE_DIR/$n" ] && echo "kept $n" || echo "gone $n"; done; done
  [ -e "$TMPDIR/s-dead/.dispatch-tmp" ] && echo "kept s-dead/.dispatch-tmp" || echo "gone s-dead/.dispatch-tmp"; }
"""


def test_a_gone_session_with_an_open_command_keeps_its_control_state():
    p = _ns(FIXTURES + CONTROL_STATE + "prompt > /dev/null\ncontrol\n" + STATE)
    assert "gone s-dead/work.txt" in p.stdout, p.stdout + p.stderr  # its temp still goes
    for s in ("s-dead", "s-live"):
        for n in (f"claude-do-task-{s}.json", f"claude-orchestrator-consent-{s}.flag", f"claude-commit-grant-{s}.json"):
            assert f"kept {n}" in p.stdout, p.stdout
    assert "kept s-dead/.dispatch-tmp" in p.stdout and "kept s-dead/.owner" in p.stdout, p.stdout


def test_control_state_past_its_own_lifetime_goes():
    body = FIXTURES + CONTROL_STATE + r"""
touch -d '-8 days' "$CLAUDE_STATE_DIR"/claude-*-s-dead.* "$CLAUDE_STATE_DIR"/claude-*-s-live.*
touch -d '-4 days' "$TMPDIR/s-dead/.dispatch-tmp" "$TMPDIR/s-dead/work.txt"
echo '{}' > "$CLAUDE_STATE_DIR/claude-do-task-s-young.json"
bash "$REPO/scripts/install/tmp-cleanup-install.sh"
control; [ -e "$CLAUDE_STATE_DIR/claude-do-task-s-young.json" ] && echo "kept young"
"""
    p = _ns(body, volsize="64m")
    for s in ("s-dead", "s-live"):
        for n in (f"claude-do-task-{s}.json", f"claude-orchestrator-consent-{s}.flag", f"claude-commit-grant-{s}.json"):
            assert f"gone {n}" in p.stdout, p.stdout + p.stderr
    assert "gone s-dead/.dispatch-tmp" in p.stdout and "kept young" in p.stdout, p.stdout


def test_a_run_with_throwaway_locations_touches_nothing_outside_them():
    """Home, state and temp are the test's own (no CLAUDE_CODE_TMPDIR, as a test sets none); the default roots of
    the namespace (/tmp, /var/tmp) hold a dead session, its command output and an old role directory, and are full.
    The reaction runs (the own volume is short too) and touches nothing but the own roots."""
    body = FIXTURES + ROLES + r"""
unset CLAUDE_CODE_TMPDIR; u=$(id -u)
for r in /tmp /var/tmp/claude-scratch; do
  mkdir -p "$r/claude-$u/-proj/s-gone/tasks"; echo out > "$r/claude-$u/-proj/s-gone/tasks/b1.output"
  touch -d '-1 hour' "$r/claude-$u/-proj/s-gone/tasks/b1.output"
done
owner /var/tmp/claude-scratch/s-gone s-gone "$D"; echo x > /var/tmp/claude-scratch/s-gone/work.txt
roles /var/tmp/claude-scratch/s-gone qa:48
dd if=/dev/zero of=/tmp/fill bs=4k 2>/dev/null; dd if=/dev/zero of=/var/tmp/fill bs=4k 2>/dev/null
world() { find /tmp /var/tmp -path /tmp/f -prune -o -printf '%p %s %T@\n' | sort; }
world > "$F/before"; prompt > "$F/notice"; world > "$F/after"
diff "$F/before" "$F/after" && echo "outside untouched"
export CLAUDE_CODE_TMPDIR=$V/cli
""" + STATE + 'cat "$F/notice"\n'
    p = _ns(body)
    assert "gone s-dead/work.txt" in p.stdout and "[space] removed" in p.stdout, p.stdout + p.stderr  # it ran
    assert "outside untouched" in p.stdout, p.stdout + p.stderr
