"""Commands the Bash rules let run by design, stated once.

The hook suites assert through the real hook that each of these runs (test_removal_policy_own_scratch.py,
test_bash_safety_command_position.py); tests/test_permission_deny_rules.py feeds the same lists through the model of
Claude Code's permission matching and asserts that no deny rule of settings.json refuses one, since a deny match wins
over a hook's allow. A new allowance written here is held by both sides.
"""

# A removal inside the calling actor's own scratch directory (lib/bash_safety_rules.py::removal_policy). Fields:
# {own} the actor's own scratch directory, {root} the project, {sid} and {agent} the session and agent ids.
OWN_SCRATCH_REMOVALS = [
    "rm -f {own}/a.txt",
    "rm -rf {own}/sub",
    "rm {own}/a {own}/sub/b",
    "rm -f .claude/scratch/{sid}/dev/{agent}/a.txt",              # relative, from the project the call runs in
    "cd {root}; rm -f .claude/scratch/{sid}/dev/{agent}/a.txt",   # after a `cd` written out
    "rm {own}/a; unlink {own}/b",
    "ls {own}; rm -f {own}/a.txt && echo done",
    "if [ -f {own}/a.txt ]; then rm {own}/a.txt; fi",
    # through a variable set to a literal earlier in the same command (2026-11-20)
    "D={own}/sub; rm -rf $D",
    "D={own}/sub; rm -rf \"$D\"",
    "S={own}; cd /; rm -f $S/a.txt $S/sub/b",
    # the recorded shape of 2026-11-19 18:04Z, neutral names
    "cd {root}/src; S={own}; rm -f $S/probe.py; time python3 tool.py --out $S/probe.json",
]

# The main agent's own: its session's scratch directory under TMPDIR ({own}).
SESSION_SCRATCH_REMOVALS = [
    "rm -f {own}/a.txt",
    "rm -rf {own}/sub",
    "rm -rf {own}/pytest-of-root/x",
]

# The service, process, disk, docker and workflow rules read command position: these only name the words, or are
# the exact harmless kill and dd forms and an fdisk listing.
COMMAND_POSITION_PASSES = [
    "kill -0 12345 && echo alive",
    "kill -l",
    "grep -rn kill -i src/",
    "fdisk -l",
    "dd if=/dev/zero of=/tmp/blob.bin bs=1k count=4",
    'grep -rn "docker compose down" docs/',
    "sed -n 1,20p /etc/docker/daemon.json",
    "grep tcp /etc/docker/daemon.json",
    'rg -n "systemctl restart nginx" docs',
    "jq .platform .claude/workflow-abc.json",
    "grep -rn killall ~/.claude/hooks/",
    # the exact harmless forms the lane names
    "kill -L",
    'kill -0 "$SERVER_PID" 2>/dev/null && echo running',
    "dd if=/dev/zero of=/dev/null bs=1k count=1",
    "dd if=in.bin of=/dev/stdout",
    "dd if=in.bin of=/dev/fd/3",
    # prose about the commands, in a heredoc written to a file
    "cat <<'EOF' > notes.md\nrun docker compose down, then systemctl restart nginx\nEOF",
]

# A down/restart/stop word that is not the compose verb (a command `exec` or `run` runs, a service name) and a prune
# flag outside `system prune` are data; dd writing stdout or an ordinary file runs.
WORD_OUTSIDE_VERB_PASSES = [
    "docker compose exec db pg_ctl stop",
    "docker compose exec app supervisorctl restart worker",
    "docker compose run --rm app ./manage.py down",
    "docker compose logs -f stop",
    "docker system --help prune -a",
    "dd if=in.bin of=/dev/stdout 2>/dev/null",
    "dd if=in.bin of=out.img 2>dd.log",
    "git -C . mv notes.md docs/notes.md",
]

# The kill probe and a double-slash stdout target still pass.
PROBE_PASSES = [
    'kill -0 "$SERVER_PID" 2>/dev/null && echo running',
    "dd if=in.bin of=//dev/stdout",
]
