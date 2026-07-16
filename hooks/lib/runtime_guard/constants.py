#!/usr/bin/env python3
"""Pure data-table vocabularies for the protected-runtime guard.

Dependency LEAF: defines only literal frozenset/dict constants, imports nothing,
references nothing from _core. The decision anchors `_block`, the `Verdict` type
alias, and `ALLOW` stay in _core by design; only pure data lives here. See
docs/reference/monolith-split-plan.md for the decomposition rationale and the
INV-3 dual-context import contract. ZERO project identifiers.
"""

# ── Generic verb / keyword vocabularies (no project names) ───────────────────
PKG_MANAGERS = frozenset({"yarn", "npm", "pnpm", "bun"})
# Generic command wrappers that prefix the real command. After consuming a
# wrapper (and its own operands) the real command word follows. Includes
# process-handoff wrappers (setsid/systemd-run/daemonize) so a launch through
# them still reaches the runtime/protected command word.
ENV_WRAPPERS = frozenset({
    "env", "sudo", "command", "nohup", "time", "timeout", "doas",
    "stdbuf", "nice", "ionice", "setsid", "systemd-run", "daemonize",
    "chrt", "taskset", "setarch", "eatmydata", "exec",
})
# `exec [-cl] [-a name] command` — only -a consumes an operand; -c/-l do not.
_EXEC_OPTS_WITH_ARG = frozenset({"-a"})
# Wrapper -> set of options that consume ONE following operand (value).
_WRAPPER_OPTS_WITH_ARG = {
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "ionice": frozenset({"-c", "--class", "-n", "--classdata", "-p", "--pid"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "systemd-run": frozenset({
        "--unit", "-u", "--property", "-p", "--slice", "--description",
        "--on-active", "--on-calendar", "--uid", "--gid", "--setenv", "-E",
        "--working-directory", "--service-type", "--nice", "-H", "--host",
        "-M", "--machine", "--on-boot", "--on-startup", "--on-unit-active",
        "--on-unit-inactive", "--timer-property",
        # NOTE: -d/--scope/-G/--pty/-t/--quiet are NO-ARG (must NOT consume an
        # operand); they are intentionally absent here.
    }),
    "chrt": frozenset({"-p"}),
    "taskset": frozenset({"-p", "-c", "--cpu-list"}),
    "setarch": frozenset(),
    "env": frozenset({"-C", "--chdir", "-u", "--unset", "-S", "--split-string"}),
    "doas": frozenset({"-u", "-C"}),
    "sudo": frozenset({"-u", "--user", "-g", "--group", "-C", "--close-from", "-D", "--chdir", "-p", "--prompt", "-U", "--other-user", "-r", "--role", "-t", "--type"}),
    "exec": _EXEC_OPTS_WITH_ARG,
}
# Wrappers that take ONE leading positional operand before the real command
# word: timeout DURATION; chrt PRIORITY; taskset MASK; setarch ARCH. For
# chrt/taskset the operand may instead be supplied via a value option
# (taskset -c <list>, chrt -p <pid>), so the leading positional is consumed
# only when no such value option already supplied it (tracked at parse time).
# setarch's ARCH is always positional; timeout's DURATION is always positional.
_WRAPPER_LEADING_POSITIONAL = frozenset({"timeout", "chrt", "taskset", "setarch"})
# Subset whose leading positional is SUPPRESSED if a value option already
# consumed an operand (so `taskset -c 0 <cmd>` exposes <cmd>, not skips it).
_WRAPPER_POSITIONAL_OPTIONAL = frozenset({"chrt", "taskset"})
RUNTIMES = frozenset({"node", "nodejs", "tsx", "bun", "deno", "ts-node", "ts-node-esm"})
# Per-runtime leading SUBCOMMANDS that precede the script positional and must be
# skipped so `deno run <path>`, `tsx watch <path>`, `bun run <path>` reach the
# protected path. These tokens are not the script; the script follows them.
_RUNTIME_SUBCOMMANDS = frozenset({"run", "watch"})
# Runtime flags that consume one following value (so the script positional is
# not mistaken for the value, and a value is not mistaken for the script).
_RUNTIME_OPTS_WITH_ARG = frozenset({
    "-r", "--require", "--loader", "--experimental-loader", "--import",
    "--env-file", "--conditions", "-C", "--cpu-prof-dir", "--heap-prof-dir",
    "--tsconfig", "--inspect-brk", "--max-old-space-size",
})
# Tokens that, after a workspace selector, must route a launch decision to P1.
EXEC_RUNNER_TOKENS = frozenset({"node", "nodejs", "tsx", "ts-node", "bun", "deno", "exec", "dlx", "npx", "bunx", "x", "run-script"})
DEP_BUILTINS = frozenset({
    "install", "i", "ci", "add", "remove", "rm", "uninstall", "un",
    "up", "upgrade", "update", "dedupe", "why", "info", "list", "ls",
    "outdated", "link", "unlink", "audit", "prune", "import",
})
MUTATION_VERBS = frozenset({
    "cp", "mv", "touch", "truncate", "dd", "install", "rsync", "tee",
    "unzip", "rename",
})
# Verbs that actually terminate a process. lsof and bare fuser are READ-ONLY
# (they list/inspect) and must NOT be treated as kills; only `fuser -k` kills.
KILL_VERBS = frozenset({"kill", "pkill", "killall"})
SERVICE_VERBS = frozenset({
    "start", "stop", "restart", "try-restart", "reload",
    "reload-or-restart", "kill", "disable", "mask", "enable",
    # additional lifecycle verbs that reload/restart a running unit
    "try-reload-or-restart", "reload-or-try-restart", "force-reload",
    "condrestart", "condreload",
})
# Generic build verbs / tool basenames for fail-closed + bare-build family.
BUILD_TOOL_BASENAMES = frozenset({"tsc", "pkgroll", "tsup", "rollup", "esbuild", "vite", "webpack"})
DEP_SHORTHAND_NPM = frozenset({"start", "stop", "restart", "test"})

# ── Read / inspection / edit ALLOWLIST (the ONLY fixed head list) ────────────
# The anchor primitive (_p0_anchor) is HEAD-AGNOSTIC: it does NOT decide based on
# the leading program / wrapper name. The single fixed list it consults is this
# small, stable set of read / search / listing / stat / diff / pager / text-editor
# operations. A simple command whose HEAD basename is in this set is treated as a
# data/inspection command — its arguments are DATA (a protected path/command named
# as a grep pattern, an echo argument, a cat target, a diff operand) and the anchor
# scan is skipped for it (so read/inspect/edit of a protected path still ALLOWS).
# Any head OUTSIDE this set is a potential exec front-end / wrapper / launcher, so
# its WHOLE argv is scanned for a protected anchor in executable position. This is
# a denylist-free design: novel exec/process wrappers are never enumerated — they
# simply are NOT in the read/inspect allowlist, so their trailing protected
# launch/build/kill is analyzed regardless of the wrapper's name.
READ_INSPECT_EDIT_ALLOWLIST = frozenset({
    # file reading / dumping / paging
    "cat", "bat", "less", "more", "head", "tail", "tac", "nl", "zcat", "zless",
    "xxd", "od", "hexdump", "strings", "view",
    # search
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "ripgrep",
    # listing / stat / metadata
    "ls", "ll", "dir", "tree", "stat", "file", "wc", "du", "df", "readlink",
    "realpath", "basename", "dirname", "pwd", "find", "fd", "locate",
    "namei", "lsattr", "getfattr",
    # diff / compare
    "diff", "colordiff", "cmp", "comm", "sdiff", "delta", "difft",
    # text transform / print (DATA emitters — never an exec launcher)
    "echo", "printf", "print", "yes", "seq", "cut", "sort", "uniq", "tr",
    "rev", "fold", "fmt", "column", "paste", "join", "expand", "unexpand",
    "jq", "yq", "awk", "gawk", "sed",
    # text editors (open a file for editing; not a launcher of the protected cmd)
    "vi", "vim", "nvim", "nano", "emacs", "ed", "code", "subl", "micro", "pico",
    # checksum / encode (read-only over file contents)
    "md5sum", "sha1sum", "sha256sum", "sha512sum", "cksum", "b2sum",
    "base64", "base32", "xargs0",
    # process / open-file inspection (read-only listing of a path/ident as DATA).
    # NOTE: the kill variants (`fuser -k`, `xargs kill`) are NOT exempted here —
    # they are caught by the cross-segment P6 process-kill guard, which inspects
    # `fuser -k` / `xargs kill` regardless of this allowlist.
    "lsof", "fuser", "ps", "pgrep", "pidof", "pstree", "top", "htop",
    # git read/inspection subset (the head is git; the verb is checked separately
    # below — git is intentionally NOT blanket-allowlisted because `git` can also
    # be a benign VCS op; handled by _git_is_readonly).
})

# git subcommands that are read-only / inspection (when head == 'git'). A git
# command with one of these verbs is treated as inspection (anchor scan skipped).
_GIT_READONLY_SUBCMDS = frozenset({
    "status", "log", "show", "diff", "blame", "ls-tree", "ls-files", "cat-file",
    "rev-parse", "describe", "branch", "tag", "remote", "config", "shortlog",
    "reflog", "grep", "whatchanged", "annotate", "for-each-ref", "rev-list",
})


# ── Generic exec-front-end profiles (recursive execution-tail) ───────────────
# A documented pass-through exec front-end is a wrapper that, after consuming its
# OWN options/operands, exec()s a TRAILING command (its "execution tail"). Unlike
# the ENV_WRAPPERS set above — which the command-word scanner folds away in place
# under a fixed handful of option grammars — these profiles drive a RECURSIVE
# pre-pass: the front-end is peeled off and the remaining tail is re-analyzed by
# the full primitive set (P1/P2/P6/P8/P9). This makes launch/kill/build detection
# wrapper-AGNOSTIC: an UNKNOWN binary is NOT a front-end (so a benign tail stays
# allowed), but every documented routine front-end exposes its trailing command
# to the guard so a protected launch/kill behind it can no longer hide.
#
# A profile is a dict:
#   opts_with_arg : frozenset of options that consume ONE following operand.
#   leading_positionals : count of bare positional operands the front-end takes
#                         BEFORE the tail command (e.g. flock LOCKFILE; nsenter
#                         has none positional — its target is opt-supplied).
#   payload_opt : option whose VALUE is a SHELL STRING the front-end runs via a
#                 shell (flock -c / su -c / runuser -c). The value is recursed
#                 through evaluate(), not treated as an argv tail.
#   joins_tail_as_shell : True when the front-end joins its WHOLE trailing argv
#                         into a single shell-evaluated string (watch <cmd...>),
#                         so the joined tail is recursed through evaluate().
# Options not listed are treated as no-arg flags (skipped). Unknown long opts of
# the `--opt=value` fused form are single tokens. A fused short opt (`-fXYZ`) is
# a single token. `--` ends option scanning; the next token starts the tail.
EXEC_FRONTEND_PROFILES = {
    # singleton-daemon launcher: `flock [opts] LOCKFILE cmd...` OR `flock -c 'str'`
    "flock": {
        "opts_with_arg": frozenset({"-w", "--timeout", "-E", "--conflict-exit-code"}),
        "leading_positionals": 1,
        "payload_opts": frozenset({"-c", "--command"}),
    },
    # sandbox: `firejail [opts] cmd...` (its own opts are mostly --opt=value)
    "firejail": {"opts_with_arg": frozenset(), "leading_positionals": 0},
    # namespace: `unshare [opts] cmd...`. `--wd <dir>` chdirs the wrapped cmd.
    "unshare": {
        "opts_with_arg": frozenset({
            "--map-user", "--map-group", "--setgroups", "--wd", "--wd=",
            "--mount", "--propagation", "-S", "--setuid", "-G", "--setgid",
        }),
        "leading_positionals": 0,
        "cwd_opts": frozenset({"--wd"}),
    },
    # enter ns: `nsenter [opts] cmd...`
    "nsenter": {
        "opts_with_arg": frozenset({
            "-t", "--target", "-S", "--setuid", "-G", "--setgid",
            "--wd", "--wdns", "-T", "--timens",
        }),
        "leading_positionals": 0,
    },
    # privilege switch: `runuser -u USER -- cmd...` OR `runuser [opts] USER -c 'str'`
    # runuser also accepts the USER as an optional LEADING positional (the form
    # without -u): `runuser root -c 'str'`. Treat a bare positional before the
    # payload/tail as the user operand (consume_user_positional).
    "runuser": {
        "opts_with_arg": frozenset({"-u", "--user", "-g", "--group", "-G", "--supp-group", "-s", "--shell"}),
        "leading_positionals": 0,
        "consume_user_positional": True,
        "payload_opts": frozenset({"-c", "--command", "--session-command"}),
    },
    # privilege switch: `su [opts] [USER] -c 'str'` OR `su USER cmd?`. The USER is
    # an optional leading positional; -c/--command/--session-command may appear
    # before OR after it. Consume one bare positional as the user before the tail.
    "su": {
        "opts_with_arg": frozenset({"-g", "--group", "-G", "--supp-group", "-s", "--shell"}),
        "leading_positionals": 0,
        "consume_user_positional": True,
        "payload_opts": frozenset({"-c", "--command", "--session-command"}),
    },
    # trace: `strace [opts] cmd...`
    "strace": {
        "opts_with_arg": frozenset({"-o", "-p", "-e", "-s", "-a", "-E", "-P", "-S", "-u", "-I", "-b", "-x"}),
        "leading_positionals": 0,
    },
    "ltrace": {
        "opts_with_arg": frozenset({"-o", "-p", "-e", "-s", "-a", "-E", "-l", "-u", "-n"}),
        "leading_positionals": 0,
    },
    # repeat-watch: `watch [opts] cmd...` (joins tail into a shell-evaluated str)
    "watch": {
        "opts_with_arg": frozenset({"-n", "--interval", "-d", "--differences"}),
        "leading_positionals": 0,
        "joins_tail_as_shell": True,
    },
    # cpu cap: `cpulimit [opts] -- cmd...`
    "cpulimit": {
        "opts_with_arg": frozenset({"-l", "--limit", "-p", "--pid", "-e", "--exe", "-c", "--cpu"}),
        "leading_positionals": 0,
    },
    # privilege drop: `setpriv [opts] cmd...`
    "setpriv": {
        "opts_with_arg": frozenset({
            "--reuid", "--regid", "--groups", "--inh-caps", "--ambient-caps",
            "--bounding-set", "--securebits", "--selinux-label", "--apparmor-profile",
        }),
        "leading_positionals": 0,
    },
    # resource limit: `prlimit [opts] cmd...`
    "prlimit": {
        "opts_with_arg": frozenset({"-p", "--pid"}),
        "leading_positionals": 0,
    },
    # perf: `perf <subcmd> [opts] cmd...` — its subcmd (stat/record/trace) is a
    # leading positional; opts before the tail are mostly --opt=value or no-arg.
    "perf": {
        "opts_with_arg": frozenset({"-o", "--output", "-p", "--pid", "-e", "--event", "-C", "--cpu"}),
        "leading_positionals": 1,
    },
    # valgrind: `valgrind [opts] cmd...` (opts are --opt=value)
    "valgrind": {"opts_with_arg": frozenset(), "leading_positionals": 0},
    # record-replay: `rr record cmd...` / `rr cmd...` — subcmd is a leading pos.
    "rr": {
        "opts_with_arg": frozenset({"-o", "--output-trace-dir"}),
        "leading_positionals": 1,
    },
    # bubblewrap: `bwrap [opts] cmd...`. `--chdir <dir>` chdirs the wrapped cmd.
    "bwrap": {
        "opts_with_arg": frozenset({
            "--bind", "--ro-bind", "--dev-bind", "--chdir", "--setenv",
            "--unsetenv", "--uid", "--gid", "--hostname", "--proc", "--dev", "--tmpfs",
        }),
        "leading_positionals": 0,
        "cwd_opts": frozenset({"--chdir"}),
    },
    # chroot: `chroot [opts] NEWROOT cmd...` (NEWROOT relocates the fs root — a
    # protected RELATIVE tail under it cannot be proven non-protected; the
    # leading-positional consumption + tail re-analysis stays conservative).
    "chroot": {
        "opts_with_arg": frozenset({"--userspec", "--groups"}),
        "leading_positionals": 1,
    },
    # proot: `proot [opts] cmd...`. `-w/--cwd <dir>` chdirs the wrapped cmd.
    "proot": {
        "opts_with_arg": frozenset({"-r", "--rootfs", "-w", "--cwd", "-b", "--bind", "-q", "--qemu", "-k", "--kernel-release"}),
        "leading_positionals": 0,
        "cwd_opts": frozenset({"-w", "--cwd"}),
    },
    # virtual X server: `xvfb-run [opts] cmd...`
    "xvfb-run": {
        "opts_with_arg": frozenset({"-n", "--server-num", "-s", "--server-args", "-f", "--auth-file", "-e", "--error-file", "-w", "--wait"}),
        "leading_positionals": 0,
    },
    # dbus session: `dbus-run-session [opts] -- cmd...`
    "dbus-run-session": {
        "opts_with_arg": frozenset({"--config-file", "--dbus-daemon"}),
        "leading_positionals": 0,
    },
    # gdb: `gdb [opts] --args cmd...` — the tail begins ONLY after `--args`.
    "gdb": {"opts_with_arg": frozenset({"-x", "--command", "-ex", "--eval-command"}), "leading_positionals": 0, "args_marker": "--args"},
    # lock-while-running variants of repeat: `repeat`/`timeout` already in
    # ENV_WRAPPERS; do not duplicate here.
}
