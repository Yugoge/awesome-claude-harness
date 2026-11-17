#!/usr/bin/env python3
"""The rules of hooks/pretool-bash-safety.sh, one predicate each, run in one interpreter.

Usage: bash_safety_rules.py <hooks dir>  (the PreToolUse payload on stdin)

Exits 2 on a refusal, its message on stderr; otherwise prints ALLOW, CONSENT (main-agent /do consent) or
SENTINEL <task id> (a structured /allow grant). The shell entry allows CONSENT and SENTINEL after the pre-clean
snapshot guard and refuses anything else (no token, a crash, a wrong interpreter). The runtime, commit and
session_dirs.txt guards and the /do consent-flag rule run before the /do and /allow releases and neither releases
them; every later rule is released by both. A view that cannot be built degrades to the raw command, so a broken
helper refuses more, never less.
"""
import contextlib
import json
import os
import re
import resource
import signal
import subprocess
import sys

HOOKS = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(HOOKS, "lib")
sys.path[:0] = [p for p in (HOOKS, LIB) if p not in sys.path]


def refuse(*lines):
    """Refuse the call: the lines go to stderr, and the process exits 2, which the shell entry relays."""
    sys.stderr.write("".join(line + "\n" for line in lines))
    sys.stderr.flush()
    sys.exit(2)


def released_line():
    return "Release: the user can authorize this command with /do or a matching /allow grant."

def lines_of(text):
    return text.split("\n")


def grep(pattern, text):
    """`grep -qE`: a match on any line of text."""
    rx = re.compile(pattern) if isinstance(pattern, str) else pattern
    return any(rx.search(line) for line in lines_of(text))


def state_dir():
    """The hook state root as lib/harness_state_dir.sh resolves it."""
    v = os.environ.get("CLAUDE_STATE_DIR", "")
    return (v.rstrip("/") or "/") if v.startswith("/") else "/tmp"


def one_slash(d):
    """`${d%/}`: the directory without one trailing slash."""
    return d[:-1] if d.endswith("/") else d


def with_alarm(seconds, fn, *args):
    """fn(*args) under a wall-clock limit; raises TimeoutError past it."""
    def _alarm(signum, frame):
        raise TimeoutError
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def duration(text, default):
    """A GNU `timeout` duration in seconds (0 = no limit); None when timeout would reject it."""
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([smhd]?)", text or default)
    if not m:
        return None
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


# ── Runtime guard (before /do and /allow) ────────────────────────────────────

_RG_PRE = r"""(^|[;&|]|\s)["']?([^\s;&|"']*/)?"""
_RG_POST = r"""["']?(\s|$)"""
RUNTIME_FALLBACK = [re.compile(p, re.I) for p in (
    r"(^|[;&|]|\s)(systemctl|service)\s+(start|stop|restart|try-restart|reload|reload-or-restart|kill|disable|mask|enable)(\s|$)",
    _RG_PRE + r"(killall|kill|pkill|fuser)" + _RG_POST,
    r"(^|[;&|]|\s)(yarn|npm|pnpm|bun)(\s|$)",
    r"(^|[;&|]|\s)(npx|bunx|tsc|pkgroll|tsup)(\s|$)",
    r"(^|[;&|]|\s)(node|nodejs|tsx|deno)(\s|$)",
    _RG_PRE + r"(netcat|ncat|nc|socat|telnet|curl|wget|httpie|https|http)" + _RG_POST,
)]


def runtime_fallback_denies(command):
    """The danger families the runtime guard protects, read from raw text, for when the engine gave no verdict.

    Coarser than the engine in both directions: it denies a bare `kill <pid>` the engine allows, and it misses
    forms the engine normalises (`"cu"rl`, `\\curl`, `$(...)`). It runs only after the engine failed to decide.
    hooks/tests/test_fail_closed_drift.py checks that every kill and endpoint front-end of the engine is covered.
    """
    return any(grep(rx, command) for rx in RUNTIME_FALLBACK)


def runtime_guard(payload_text, command):
    """BS-02 and BS-03: the protected-runtime engine, then its fail-closed fallback."""
    verdict, reason = "MISSING", ""
    if os.path.isfile(os.path.join(LIB, "runtime_guard.py")):
        try:
            from runtime_guard import _core
            try:
                payload = json.loads(payload_text)
            except ValueError:
                payload = None
            if payload is None:
                verdict = "INDETERMINATE"
            elif payload.get("tool_name") != "Bash":
                verdict = "ALLOW"
            else:
                ti = payload.get("tool_input") or {}
                cwd = ti.get("cwd") or os.environ.get("CLAUDE_GUARD_CWD") or os.getcwd()
                import io
                err, sys.stderr = sys.stderr, io.StringIO()
                try:
                    decision, primitive, why = _core.evaluate(ti.get("command", ""), cwd)
                    verdict = "BLOCK" if decision == "BLOCK" else "ALLOW"
                    if verdict == "BLOCK":
                        reason = sys.stderr.getvalue() + f"[protected-runtime-guard] BLOCK {primitive}: {why}"
                except BaseException:  # noqa: BLE001 - an engine crash is a missing verdict, never an allow
                    verdict = "INDETERMINATE"
                finally:
                    sys.stderr = err
        except BaseException:  # noqa: BLE001
            verdict = "INDETERMINATE"
    if verdict == "BLOCK" and "[protected-runtime-guard] BLOCK STEP1: " in reason:
        # STEP1: the policy file is unusable, not the command protected; the reason names the defect and its repair.
        refuse(reason,
                   "BLOCKED: protected-runtime-guard — its policy file is unusable, so this service-control/"
                   "process-kill/package-manager/build/runtime command is refused until the file is repaired. This "
                   "block is unbypassable (it runs before /do and /allow).",
                   "Run the recovery named above, then retry; commands outside those families still run.")
    if verdict == "BLOCK":
        refuse(reason,
                   "BLOCKED: protected-runtime-guard — this command could restart, hand off, or kill a protected local "
                   "service, or rebuild/launch its protected package. This block is generic and unbypassable (it runs "
                   "before /do and /allow).",
                   "If the human operator intends to run it, they must do so from a real terminal — Claude/subagents "
                   "are never permitted this command.")
    if verdict != "ALLOW" and runtime_fallback_denies(command):
        refuse(f"BLOCKED: protected-runtime-guard FAIL-CLOSED — the guard engine is unavailable or returned no "
                   f"decision (verdict='{verdict}'), and this command is in a protected verb family (service-control/"
                   f"process-termination/package-manager/build/runtime/endpoint-client). Denied conservatively. A "
                   f"human operator must run it from a real terminal, and the guard deployment "
                   f"({os.path.join(LIB, 'runtime_guard.py')}) should be repaired.")


# ── Commit guard (before /do and /allow) ─────────────────────────────────────

def commit_guard_applies(command):
    s = re.sub(r"""['"\\]""", "", command)
    return ("commit" in s or "config" in s) and re.search(r"(^|[^\w])git", s) is not None


def commit_guard(payload):
    """BS-04, BS-05, BS-06: 'HOOKS <why>', 'CONFIG <key>', 'FILTER <top>[\\t<why>]' or 'OK'.

    (1) a commit that skips the hooks: --no-verify..--no-ver, -n in a short cluster, a core.hooksPath/include/
    GIT_CONFIG_* override, or a `-c alias.X=` call whose expansion skips them (name matched case-insensitively as git
    does; a `!`-shell alias's child git inherits the outer -c; a chain past the expansion limit fails closed);
    (2) a git config write to alias.*, core.hooksPath, filter.claude-settings.*, include(.path) or includeIf.*.path
    that can reach the harness home (global/system, a named file, the harness or an unresolved repository, nested,
    wrapper-flagged), not a plain local write elsewhere or a read;
    (3) a commit whose repository has settings.json changed against HEAD while the claude-settings filter is not
    registered. Text the guard cannot split like the shell fails closed.
    """
    import importlib.util as iu
    import itertools
    import shlex
    H = HOOKS
    from lib.git_command_classifier import _command_token_index, _git_subcommand
    from lib.claude_home import load_settings
    s = iu.spec_from_file_location('_overnight_guard', H + '/pretool-overnight-hook-guard.py')
    og = iu.module_from_spec(s)
    s.loader.exec_module(og)
    d = payload
    cur = [d.get('cwd') or os.getcwd()]
    dirs = cur[:]
    commits, why, cfg, loc, ex = [], [], [], [], {}
    LONGV = ('message', 'file', 'reuse-message', 'reedit-message', 'template', 'author', 'date', 'trailer')
    GV = {'--git-dir': 'GIT_DIR', '--work-tree': 'GIT_WORK_TREE'}
    CFGW = {'set', 'unset', 'unset-all', 'replace-all', 'add', 'rename-section', 'remove-section'}
    CFGR = {'get', 'get-all', 'get-regexp', 'get-urlmatch', 'list'}
    WRF = {'--unset', '--unset-all', '--add', '--replace-all', '--rename-section', '--remove-section'}
    RDF = {'--get', '--get-all', '--get-regexp', '--get-urlmatch', '--get-color', '--get-colorbool', '--list', '-l'}

    def prot(k):
        k = k.strip().strip('\'"').lower()
        return k in ('core', 'alias', 'filter', 'filter.claude-settings', 'include') or k.startswith(
            ('alias.', 'filter.claude-settings.')) or og._config_key_redirects_keystone(k)

    def at(base, p):
        return os.path.join(base, os.path.expanduser(os.path.expandvars(p)))

    def words(t):  # shell words; separators, comments and newlines kept as the shell sees them
        t = re.sub(r'&>', '>', re.sub(r'([<>])&', r'\1 ', re.sub(r'(?<=[^\s;&|()`])#', '_', t.replace('\\\n', ''))))
        for tail in ('', '"', "'"):
            x = shlex.shlex(t.replace('\n', '\n;') + tail, posix=True, punctuation_chars=';&|()`')
            x.whitespace_split = True
            with contextlib.suppress(ValueError):
                return list(x)
        return t.split()

    UQ, DQ = (re.compile(p) for p in (
        r"""(?P<e>\\[\s\S])|(?P<s>'[^']*'|\$'(?:\\[\s\S]|[^\\'])*')|(?P<b>`(?:\\[\s\S]|[^\\`])*`)|\$\{\w*\}|(?P<o>\$?\()|(?P<c>\))|(?P<d>")|(?P<m>(?<![^\s;&|()`])#[^\n]*)|(?P<x>\$\{|<<|\bcase\b|['`])|[^\\$'`"()<#c]+|[\s\S]""",
        r"""(?P<e>\\[\s\S])|(?P<b>`(?:\\[\s\S]|[^\\`])*`)|\$\{\w*\}|(?P<o>\$\()|(?P<d>")|(?P<x>\$\{|`)|[^\\`$"]+|[\s\S]"""))

    def gitish(s):
        s = re.sub(r'[\'"\\]', '', s)
        return re.search(r'(^|\W)git', s) and re.search('commit|config', s)

    def unread(what):  # text the guard cannot split like the shell: fail closed
        why.append(what)
        commits.append(('-C', cur[0]))

    def defuse(t, i=0, st='', o=''):
        """t with each $( and ` the shell leaves unrun ('..', $'..', \\-escaped, # comment) made inert; t if unsure."""
        while i < len(t) and st[-1:] != '!':
            m = (DQ if st[-1:] == '"' else UQ).match(t, i)
            k, s, i = m.lastgroup, m.group(), m.end()
            o += s.translate({36: '_', 96: ')'}) if k in ('e', 's') else s
            if k == 'd' and st[-1:] == ')' and '"' in st and re.search(r'(^|[\s;&|(])(-\w*c|eval)\s+"$', o) and gitish(t[i:]):
                unread('a double-quoted bash -c/eval string inside a double-quoted $(...)')
            st = st + '!' if k == 'x' and (s != '${' or st) or k == 'c' and st[-1:] != ')' else st[:-1] if k == 'c' or k == 'd' and st[-1:] == '"' else st + {'o': ')', 'd': '"'}.get(k, '')
        return t if st else o

    def scan(text, depth=0, lg=False, gc=()):  # lg: quotes gone, so every $( and ` counts; gc: inherited -c globals
        if depth >= 5:
            return unread('nesting past the expansion limit') if gitish(text) else None
        t = heredoc_data_blanked(text)
        w = words(t)
        for sep, grp in itertools.groupby(zip(w, w if lg else words(defuse(t))),
                                          lambda p: p[0] != '' and set(p[0]) <= set(';&|()`')):
            if not sep:
                one(*map(list, zip(*grp)), depth, lg, gc)

    def one(t, u, depth, lg, gc):  # u: t's words with unrun $( and ` made inert
        for w, v in zip(t, u):
            if '$(' in v or '`' in v:
                scan(w, depth + 1, True)
            if (a := re.match(r'[A-Za-z_]\w*=', w)) and og._GIT_HOOK_SUPPRESS_RE.search(a.group(0)):
                why.append(a.group(0) + '... assignment')
        if (i := _command_token_index(t)) is None:
            return
        if ' ' in t[i]:
            return scan(' '.join(t[i:]), depth + 1, lg, gc)
        b, c = os.path.basename(t[i]), [j for j in range(i + 1, len(t) - 1) if re.match(r'-[^-]*c', t[j])]
        if b in ('bash', 'sh', 'zsh', 'dash', 'ksh') and c:
            scan(t[c[0] + 1], depth + 1, lg, gc)
        if b in ('cd', 'pushd'):
            cur[0] = at(cur[0], ([a for a in t[i + 1:] if a[:1] != '-'] or ['~'])[0])
            dirs.append(cur[0])
        if b != 'git':
            return ex.update(a.split('=', 1) for a in t[i + 1:] if '=' in a) if b == 'export' else None
        g = t[i + 1:]
        sub, rest = _git_subcommand(g)
        base = cur[0]
        ev = {**ex, **dict(a.split('=', 1) for a in t[:i] if '=' in a)}
        for j, w in enumerate(g[:len(g) - len(rest)]):  # -C moves base; --git-dir/--work-tree set GIT_DIR/GIT_WORK_TREE
            if w == '-C' and j + 1 < len(g):
                base = at(base, g[j + 1])
                dirs.append(base)
            if w.split('=')[0] in GV:
                ev[GV[w.split('=')[0]]] = w.split('=', 1)[1] if '=' in w else ''.join(g[j + 1:j + 2])
        if og._git_invocation_injects_keystone_config([*gc, *g]):
            why.append('a core.hooksPath/include config override')
        if sub == 'config':
            # ix: words that can be the verb or the key; n: the key. git's options end at the key, so each later
            # word is an operand. A rename (option abbreviated too) checks its new name as a section as well.
            ix = [j for j, a in enumerate(rest) if a[:1] != '-' and not (j and re.fullmatch(r'-[^-f]*f|--file?', rest[j - 1]))]
            vb, wf = rest[ix[0]] if ix else '', any(o in WRF for o in rest)
            n = (ix[(vb in CFGW and not wf):] or [len(rest)])[0]
            rn = any(len(o) > 4 and '--rename-section'.startswith(o) for o in rest[:n]) or vb == 'rename-section' and not wf
            wr = wf or not (any(o in RDF for o in rest[:n]) or vb in CFGR) and (vb in CFGW or len(rest) > n + 1)
            tgt = next((a for j, a in enumerate(rest[n:n + 1 + rn]) for e in ('', '.path')[:1 + j] if prot(a + e)), '')
            # A literal absolute -C/--git-dir/GIT_DIR prefix names the repository whatever the cwd.
            gl = g[:len(g) - len(rest) - 1]
            pin = not {'GIT_DIR', 'GIT_WORK_TREE'} & {*ex} and any(
                p[:1] == '/' and not re.search('[$`]', p) for p in [
                    *(gl[j + 1] for j, w in enumerate(gl[:-1]) if w in ('-C', '--git-dir')),
                    *(w[10:] for w in gl if w.startswith('--git-dir=')),
                    *(a[8:] for a in t[:i] if a.startswith('GIT_DIR='))])
            if wr and tgt:
                if depth or {'GIT_CONFIG', 'GIT_COMMON_DIR'} & {*ev, *os.environ} or any(a[:1] == '-' for a in t[:i]) \
                        or any(re.match(r'-[^-]*f|--(fil|gl|sy)', a) for a in rest):
                    cfg.append(tgt)
                else:
                    loc.append((tgt, [] if pin else [*dirs],
                                ('-C', base, *(o + '=' + at(base, ev[k]) for o, k in GV.items() if ev.get(k)))))
            return None
        gr = [*gc, *(g[:len(g) - len(rest) - 1] if sub else [])]  # `-c alias.X=`: inherited, then this call's own
        al = {kv.strip('\'"').lower().split('=', 1)[0][6:]: (kv.split('=', 1)[1] if '=' in kv else '') if w[:2] == '-c' else None
              for k2, w in enumerate(gr)
              if (kv := (w[2:] if (w.startswith('-c') and len(w) > 2 and w[2] != 'C') else (
                  gr[k2 + 1] if w in ('-c', '--config-env') and k2 + 1 < len(gr) else (
                      w[13:] if w.startswith('--config-env=') else None))))
              and kv.strip('\'"').lower().startswith('alias.')}  # None: --config-env reads the value from the environment
        if sub and sub.lower() in al and al[sub.lower()] is None:
            why.append('an alias whose value --config-env reads from the environment')
            commits.append(('-C', base))
        elif sub and sub.lower() in al:
            v = al[sub.lower()].strip()
            if depth >= 4:
                why.append('an alias chain past the expansion limit')
                commits.append(('-C', base))
            else:
                scan((v[1:] if v[:1] == '!' else shlex.join(t[:len(t) - len(rest) - 1]) + ' ' + v) + ' ' + shlex.join(rest),
                     depth + 1, gc=gr if v[:1] == '!' else gc)
        if sub != 'commit':
            return
        commits.append(('-C', base, *(o + '=' + at(base, ev[k]) for o, k in GV.items() if ev.get(k))))
        skip = False
        for a in rest:
            if skip:
                skip = False
                continue
            if a == '--':
                break
            n = a[2:].split('=')[0]
            if a.startswith('--'):
                if len(n) >= 6 and 'no-verify'.startswith(n):
                    why.append(a)
                skip = '=' not in a and n != '' and any(o.startswith(n) for o in LONGV)
            else:
                for k, ch in enumerate(a[1:] if a.startswith('-') else ''):
                    if ch == 'n':
                        why.append('-n in ' + a)
                        break
                    if ch in 'mFcCtuS':
                        skip = ch in 'mFcCt' and k == len(a) - 2
                        break

    scan(d.get('tool_input', {}).get('command', ''))

    def git(r, *a):
        return subprocess.run(['git', *r, *a], capture_output=True, text=True, timeout=20)

    def cdir(r):  # '' = no repository
        return (o := git(r, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()) and os.path.realpath(o)

    cfg = cfg + [k for k, ds, r in loc
                 if not (c := cdir(r)) or (hc := cdir(('-C', os.path.dirname(H)))) and hc in {c, *(cdir(('-C', x)) for x in ds)}]
    if cfg:
        return 'CONFIG ' + str(cfg[0])
    if commits and why:
        return 'HOOKS ' + str(why[0])
    for r in dict.fromkeys([('-C', x) for x in dirs] + commits if commits else []):
        top = git(r, 'rev-parse', '--show-toplevel').stdout.strip()
        r += ('-C', top)
        if top and git(r, 'check-attr', 'filter', '--', 'settings.json').stdout.strip().endswith(': claude-settings') \
                and git(r, 'config', '--local', '--get', 'filter.claude-settings.clean').returncode \
                and ((bad := load_settings(os.path.join(top, 'settings.json'))[1])
                     or any(git(r, 'diff', '--quiet', '--no-ext-diff', '--no-textconv', *c, 'HEAD', '--', 'settings.json').returncode
                            for c in ((), ('--cached',)))):
            return 'FILTER ' + top + ('\t' + bad if bad else '')
    return 'OK'


def run_commit_guard(payload, command, home):
    if not commit_guard_applies(command):
        return
    try:
        verdict = commit_guard(payload) if isinstance(payload, dict) else ''
    except Exception:  # noqa: BLE001 - no verdict is a refusal
        verdict = ''
    if verdict == 'OK':
        return
    elif verdict.startswith('HOOKS '):
        refuse(f"BLOCKED: commit-hook-bypass — git commit with {verdict[6:]} would skip the commit hooks; FORBIDDEN "
                   f"for every caller", f"Command: {command}")
    elif verdict.startswith('CONFIG '):
        refuse(f"BLOCKED: config-keystone-write — git config write to {verdict[7:]} (core.hooksPath / alias.* / "
                   f"filter.claude-settings.* / include(.path) / includeIf.*.path) that can reach the harness "
                   f"(global/system config, a named file, the harness repository {home} or an unresolved one, a nested "
                   f"or wrapper-flagged call) is FORBIDDEN for every caller; a plain local write in another repository "
                   f"is not", f"Command: {command}")
    elif verdict.startswith('FILTER '):
        top, _, bad = verdict[7:].partition('\t')
        lines = [f"BLOCKED: unregistered-settings-filter — settings.json has local changes and the settings filter is "
                 f"not registered in {top}", f"Command: {command}", f"Run scripts/bootstrap in {top} first, then retry."]
        if bad:
            lines.append(f"settings.json is unusable: {bad}")
        refuse(*lines)
    else:
        refuse("BLOCKED: commit-guard FAIL-CLOSED — the commit-hook-bypass / config-keystone-write / "
               "unregistered-settings-filter guard returned no verdict", f"Command: {command}")


# ── Views for the released rules ─────────────────────────────────────────────

def heredoc_data_blanked(text):
    """text with the body of each heredoc no shell reads blanked, newlines kept; text when it does not parse."""
    from lib.shell_parse import parse, walk
    script = parse(text)
    if script.error is not None:
        return text
    read = {s.script.source for s in walk(script, into=("cmdsub", "backtick", "procsub", "heredoc_shell", "pipe_shell"))
            if s.context[-1] in ("heredoc_shell", "pipe_shell")}
    out = list(text)
    for site in walk(script, into=("cmdsub", "backtick", "procsub")):
        for r in site.cmd.redirects:
            if r.hd is not None and r.hd.body not in read:
                a, b = r.hd.body_span
                out[max(a, 0):b] = [c if c == "\n" else " " for c in out[max(a, 0):b]]
    return "".join(out)


class GitView:
    """The git invocations lib/shell_parse.py reads, nested shells included; none, and not ok, when it cannot parse."""

    def __init__(self, command):
        self.ok, self.invs = False, []
        try:
            from lib.shell_parse import git_invocations, parse
            script = parse(command)
            if script.error is None:
                self.invs = [{"subcommand": g.subcommand, "args": [a if a is not None else "" for a in g.args],
                              "path_qualified": g.path_qualified, "nested": g.context != ("top",), "git": g}
                             for g in git_invocations(script)]
                self.ok = True
        except Exception:  # noqa: BLE001
            self.ok, self.invs = False, []

    def any_sub(self, sub):
        return any(i["subcommand"] == sub for i in self.invs)

    def outer(self, sub):
        """Path-qualified or nested invocations of sub, when the command has any path-qualified or nested git."""
        if not any(i["path_qualified"] or i["nested"] for i in self.invs) or not self.any_sub(sub):
            return []
        return [i for i in self.invs if (i["path_qualified"] or i["nested"]) and i["subcommand"] == sub]


# ── Daemon, grant-flag and commit-artifact rules ─────────────────────────────

DAEMON_VERBS = r"(stop|restart|disable|enable|reload|kill|try-restart|reload-or-restart)"


def consume_daemon_restart_grant(unit, verb, payload, grant_dir, prefix):
    """Atomically consume <grant dir>/claude-allow-daemon-restart-<target>.flag; True when a valid grant was spent."""
    import fcntl
    import time
    from datetime import datetime, timezone
    target = "default" if unit == prefix else unit[len(prefix) + 1:] if unit.startswith(prefix + "-") else ""
    if not target:
        return False
    sid = str(payload.get("session_id", "") or os.environ.get("CLAUDE_SESSION_ID", "default")) or "default"
    flag = f"{one_slash(grant_dir)}/claude-allow-daemon-restart-{target}.flag"
    if not os.path.isfile(flag):
        return False
    fd = None
    try:
        fd = os.open(flag + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        for attempt in range(3):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == 2:
                    return False
                time.sleep(0.1)
        if not os.path.exists(flag):
            return False
        try:
            data = with_alarm(1, lambda: json.load(open(flag)))
            exp = datetime.fromisoformat(data.get("expires_at", "").replace("Z", "+00:00"))
            expired = (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) <= datetime.now(timezone.utc)
        except BaseException:  # noqa: BLE001 - an unreadable or undated grant is no grant
            return False
        gsid = data.get("session_id", "")
        if expired or data.get("target", "") not in (target, "all") or gsid and gsid not in ("no-active-session", sid):
            return False
        with contextlib.suppress(FileNotFoundError):
            os.unlink(flag)
        sys.stderr.write(f"[daemon-restart-grant] consumed grant for target={target} unit={unit} verb={verb}\n")
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)


def daemon_restart(command, payload, prefix):
    """The runtime guard, given the daemon family (`<prefix>`, `<prefix>-*`) as its only protected service, refuses the
    command, and the parser reads a restart verb of DAEMON_VERBS on the systemctl or service command it runs."""
    try:
        from runtime_guard import _core
        from runtime_guard.config import REQUIRED_KEYS
        from lib.shell_parse import parse, resolve, walk
        cfg = {"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}, "protected_services": [prefix, prefix + "-*"]}
        cwd = (payload.get("tool_input") or {}).get("cwd") or os.getcwd()
        verbs = DAEMON_VERBS[1:-1].split("|")
        return _core.evaluate(command, cwd, cfg)[0] == "BLOCK" and any(
            r.name in ("systemctl", "service") and any(a in verbs for a in r.argv())
            for r in (resolve(site.cmd) for site in walk(parse(command))))
    except Exception:  # noqa: BLE001 - the guard or the parser unavailable: the raw reading, which over-blocks
        return grep(r"systemctl\s+" + DAEMON_VERBS + r"(\s+|\b)", command) and grep(re.escape(prefix), command)


def daemon_rules(command, payload, env):
    """BS-09, BS-10, BS-12, BS-13: the protected daemon (inert while CLAUDE_PROTECTED_DAEMON_PREFIX is unset)."""
    prefix, targets = env["prefix"], env["targets"]
    hint = env["grant_hint"]
    if prefix:
        prefix_re = re.escape(prefix)
        if daemon_restart(command, payload, prefix):
            alt = "|".join(re.sub(r"([][\\.^$*+?(){}])", r"\\\1", t) for t in targets.split("|")) if targets else ""
            unit_re = re.compile(prefix_re + (f"(-({alt}))?" if alt else ""))
            unit = next((m.group(0) for line in lines_of(command) for m in [unit_re.search(line)] if m), "")
            unit = unit[:-8] if unit.endswith(".service") else unit
            vm = next((m for line in lines_of(command) for m in [re.search(r"systemctl\s+" + DAEMON_VERBS, line)] if m), None)
            verb = vm.group(1) if vm else ""
            if not (unit and consume_daemon_restart_grant(unit, verb, payload, env["grant_dir"], prefix)):
                refuse(f"BLOCKED: daemon-restart-prohibition — systemctl {verb or '<verb>'} on {unit or prefix + '-*'} is refused",
                           f"Command: {command}",
                           f"REASON: no agent restarts {prefix}-* by any path.",
                           f"Hint: user must run {hint} <target> from a real TTY first.", released_line())
        if grep(prefix_re, command) and grep(r"(^|[^-\w])(systemctl|service)([^-\w]|$)", command) \
                and grep(r"(restart|stop|disable|enable|reload|kill|try-restart|reload-or-restart|kick|cycle|bounce|hup|HUP)", command) \
                and grep(r"(systemd-run|^|\s)((at|batch)\s|crontab\s|nohup\s|disown\s|watch\s|timeout\s|dbus-send|busctl|nc\s|ncat\s"
                         r"|eval\s|bash\s+-c|sh\s+-c|zsh\s+-c|python3?\s+-c|node\s+-[ce]|perl\s+-e|ruby\s+-e)", command):
            refuse("BLOCKED: daemon-restart-wrapper — wrapper invocation co-occurring with daemon-restart vocabulary is refused",
                       f"Command: {command}",
                       "REASON: an indirect daemon restart (systemd-run/at/crontab/nohup/timeout/dbus-send/nc/eval/bash -c/"
                       f"python -c) is the same restart. Use the user-only {hint} grant channel instead.", released_line())
    if grep(r"(curl|wget|nc\s|ncat|http\.client|aiohttp|requests)", command) \
            and grep(r"(localhost|127\.0\.0\.1):[0-9]+/stop", command):
        refuse("BLOCKED: daemon-restart-http-stop — HTTP /stop on a localhost port is refused", f"Command: {command}",
                   "REASON: /stop on a localhost port is a daemon's shutdown endpoint; false positives on other local "
                   "services are accepted.", released_line())
    if writes_namespace(command, re.escape(one_slash(env["grant_dir"]) + "/claude-allow-daemon-restart-")):
        refuse("BLOCKED: daemon-restart-sentinel-write — writing to the daemon-restart grant sentinel is refused",
                   f"Command: {command}",
                   f"REASON: only {hint} (run by the user from a TTY) creates the grant sentinel.", released_line())


ARTIFACT_WRITE_VERB_RE = (
    r"(\btee([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bcp(io)?([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bmv([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bln([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\btouch([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bsed\s+-i"
    r"|\bi?python([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\binstall([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bdd\s"
    r"|\btruncate([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bshred([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\brsync([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\b[gmn]?awk([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bperl([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bnode(js)?([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
    r"|\bruby([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$))"
)
"""A command word that writes a file it is handed. Each token ends at the end of its shell word, and a `/` before
that end means a directory on the way to something else, not the verb. Interpreters are here because they write
with no redirection at all."""
ARTIFACT_NS_CAPTURE_RE = r"""(^|[\s;|&(])[A-Za-z_][A-Za-z0-9_]*=['"]?"""
ARTIFACT_VAR_WRITE_RE = r"""(>>?[&|]?\s*['"]?\$\{?[A-Za-z_]|""" + ARTIFACT_WRITE_VERB_RE + r""".*\$\{?[A-Za-z_])"""


def writes_namespace(command, ns_re):
    """A write into a namespace: a redirection whose target it is, a listed verb handed it, or the namespace captured
    in a variable and then written through one (the whole command read as one line, so a heredoc body counts).

    Positional, not semantic. Residual over-block: a read is refused when an enumerated verb stands before the
    namespace for another reason, or when an interpreter does the reading. Residual under-block: a verb not listed,
    or a path assembled at run time, writes through. It raises the cost of a hand-written file; the barrier is
    hooks/pretool-git-privilege-guard.py, which honours only a pipeline-minted grant claimed by the dispatched
    subagent that holds the matching attestation.
    """
    one = command.replace("\n", " ")
    return grep(ns_re, command) and (
        grep(r""">>?[&|]?\s*['"]?""" + ns_re, command)
        or grep(ARTIFACT_WRITE_VERB_RE + ".*" + ns_re, one)
        or (grep(ARTIFACT_NS_CAPTURE_RE + ns_re, one) and grep(ARTIFACT_VAR_WRITE_RE, one))
        or grep(ARTIFACT_NS_CAPTURE_RE + ns_re + "[^;|&]*" + ARTIFACT_WRITE_VERB_RE, one))


COMMIT_GRANT_PREFIX = "claude-commit-grant-"  # the name scripts/write-commit-grant.py gives each grant


def commit_artifact_rules(command, state):
    """BS-14, BS-15, BS-16: the /commit user-intent flag, the dispatch attestation and the commit grant."""
    from lib.commit_pipeline import ATTEST_PREFIX
    base = one_slash(state)
    if writes_namespace(command, re.escape(base + "/claude-commit-userintent-")):
        refuse("BLOCKED: commit-userintent-sentinel-write — writing to the /commit mint-authorization sentinel is refused",
                   f"Command: {command}",
                   "REASON: only the UserPromptSubmit hook (fired when a human types /commit) writes this flag.",
                   released_line())
    if writes_namespace(command, re.escape(base + "/" + ATTEST_PREFIX)):
        refuse("BLOCKED: commit-dispatch-attestation-write — writing to the changelog-analyst dispatch-attestation "
                   "namespace is refused", f"Command: {command}",
                   "REASON: only hooks/pretool-commit-dispatch-attest.py (PreToolUse:Agent, fired by a real "
                   "changelog-analyst dispatch) writes these files; a Bash-written one would let a bare `git commit` "
                   "claim a pipeline run that never happened.", released_line())
    if writes_namespace(command, re.escape(base + "/" + COMMIT_GRANT_PREFIX)):
        refuse("BLOCKED: commit-grant-raw-write — hand-writing a /commit privilege-guard grant is refused",
                   f"Command: {command}",
                   "REASON: grants are minted only by scripts/write-commit-grant.py, which requires a live /commit "
                   "user-intent sentinel plus pipeline evidence and stamps minted_by on what it writes. Mint through "
                   "that script (it composes the grant path itself).", released_line())


# ── /do consent flag (before /do and /allow) ─────────────────────────────────

# The flag's name has one definition, next to its reader (lib/allowlist.has_do_consent); hooks/prompt-workflow.py
# writes it. The stem is that prefix without its leading `claude-` and trailing `-`.
from lib.allowlist import DO_CONSENT_FLAG_PREFIX as CONSENT_PREFIX, DO_CONSENT_FLAG_SUFFIX as CONSENT_SUFFIX  # noqa: E402

CONSENT_TOKEN = CONSENT_PREFIX.split("-", 1)[1].rstrip("-")
# Once a command names the flag (its text after quote removal, heredoc and here-string bodies included, comments
# excluded), every simple command in it must be one of these read-only shapes (checked per command below). Anything
# else, any unknown program included, is refused: the flag cannot be written by a program that is never run.
_CONSENT_READ_ONLY = frozenset({
    "cat", "ls", "stat", "file", "wc", "head", "tail", "diff", "cmp", "test", "[", "readlink", "realpath",
    "basename", "dirname", "md5sum", "sha1sum", "sha256sum", "sha512sum", "cksum", "cut", "tr", "nl", "od", "true",
    "false", ":", "cd", "pushd", "popd", "pwd", "grep", "egrep", "fgrep", "rg", "jq", "find", "echo", "printf",
    "sed", "awk", "gawk", "mawk", "nawk", "sort", "tee", "git"})
_CONSENT_STRICT_ARGS = frozenset({"find", "rg", "sed", "awk", "gawk", "mawk", "nawk", "sort", "git", "file", "printf"})
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"})
_CONSENT_GIT_READS = frozenset({"log", "show", "diff", "grep", "status", "blame", "shortlog", "ls-files", "rev-parse",
                                "describe"})
_CONSENT_GIT_COMMIT_OPTS = frozenset({"-a", "--all", "-q", "--quiet", "-s", "--signoff", "-v", "--verbose",
                                      "--allow-empty", "--amend", "--no-edit", "--no-verify", "-n", "--"})
_CONSENT_TMP_VARS = frozenset({"TMPDIR", "TMP", "TEMP", "TEMPDIR", "CLAUDE_TMPDIR"})
_CONSENT_DIR_CREATORS = frozenset({"touch", "mkdir", "mkfifo", "mknod"})
_CONSENT_COPIERS = frozenset({"cp", "mv", "ln", "install", "rsync", "link"})
# Tools that extract or check out files whose names they read from a file (an archive, a package, a stored gzip
# name) into a directory: program -> how _consent_unpack_dirs reads its options (rule 3b). git checkout-index
# --prefix and git init/clone are read by _consent_git_tree.
_CONSENT_UNPACKERS = {
    "tar": "tar", "bsdtar": "tar", "gtar": "tar", "unzip": "unzip", "cpio": "cpio", "bsdcpio": "cpio",
    "7z": "7z", "7za": "7z", "7zr": "7z", "gzip": "gzip", "gunzip": "gzip", "zcat": "gzip", "pigz": "gzip",
    "unpigz": "gzip", "ar": "ar", "dpkg-deb": "deb", "dpkg": "deb", "pax": "pax", "unrar": "rar", "rar": "rar",
    "unar": "unar", "lha": "lha", "lhasa": "lha"}
_CONSENT_DEVICES = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty")
_CONSENT_UNKNOWN = ("_", "BASH_REMATCH", "BASH_ARGV", "COMP_WORDS", "REPLY", "MAPFILE")


def _consent_norm(text):
    """Text with quotes, backslashes, `+` and whitespace dropped, lower-cased: `"orch" + 'estrator-con' "sent"` in an
    interpreter's code reads as the stem it spells."""
    return re.sub(r"""['"\\+\s`]""", "", text or "").lower()


def _consent_name_may_match(toks):
    """True when the glob tokens can match some `<CONSENT_PREFIX><id><CONSENT_SUFFIX>` (id: one or more characters,
    no slash): a product walk of the glob against that name's automaton."""
    pre, suf = CONSENT_PREFIX, CONSENT_SUFFIX
    p = len(pre)
    acc = p + 2 + len(suf)

    def target_moves(t):  # [(literal char or None for any non-slash, next state)]; state p+1 also moves by epsilon
        if t < p:
            return [(pre[t], t + 1)]
        if t in (p, p + 1):
            return [(None, p + 1)]
        if t < acc:
            return [(suf[t - p - 2], t + 1)]
        return []

    def closure(t):
        return {t, p + 2} if t == p + 1 else {t}

    seen, todo = set(), [(0, s) for s in closure(0)]
    while todo:
        g, t = todo.pop()
        if (g, t) in seen:
            continue
        seen.add((g, t))
        if g == len(toks):
            if t == acc:
                return True
            continue
        tok = toks[g]
        if tok[0] == "*":
            todo.append((g + 1, t))
        for ch, nt in target_moves(t):
            if tok[0] == "c" and not (tok[1] == ch if ch is not None else tok[1] != "/"):
                continue
            for s in closure(nt):
                todo.append((g if tok[0] == "*" else g + 1, s))
    return False


def _consent_same_dir(path, state):
    try:
        a = {os.path.normpath(path), os.path.realpath(path)}
        return bool(a & {os.path.normpath(state), os.path.realpath(state)})
    except (OSError, ValueError):
        return True


def _consent_sites(script, sp, depth=0):
    """walk's Sites, plus those of the substitutions in an unquoted heredoc body (walk reads them as text)."""
    for site in sp.walk(script):
        yield site
        if depth > 8:
            continue
        for red in site.cmd.redirects:
            hd = getattr(red, "hd", None)
            for part in (hd.expansions if hd is not None else ()):
                if part.body is not None:
                    yield from _consent_sites(part.body, sp, depth + 1)


def _consent_compounds(script, sp, depth=0):
    """Every compound command in ``script`` (for loops, groups ...), nested ones included."""
    if depth > 24 or script is None:
        return
    for pl, _sep in script.items:
        for stage in pl.stages:
            if isinstance(stage, sp.Compound):
                yield stage
                for body in stage.body:
                    yield from _consent_compounds(body, sp, depth + 1)


class _ConsentView:
    """What one command can do to the consent flag in `state`: variables, working directories and path words read
    as glob tokens tagged by origin (lit, glob, state: the state directory itself, unk: a value not known here)."""

    def __init__(self, sp, script, sites, command, cwd, state):
        self.sp, self.state = sp, state
        self.state_is_tmp = _consent_same_dir(state, "/tmp")
        self.home = os.environ.get("HOME", "")
        self.command = command
        self.defs = {}  # variable -> list of ("static", text) | ("word", Word) | ("text", source text) | ("state",)
        self._memo, self._busy = {}, set()
        for s in sites:
            cmd = s.cmd
            for a in cmd.assignments:
                self._define(a.name, a)
            r = sp.resolve(cmd)
            if r.name in ("export", "declare", "typeset", "local", "readonly"):
                for w in r.args:
                    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?\+?=", w.raw.text)
                    if m:
                        self._define(m.group(1), sp.Assignment(w))
            if r.name in ("read", "mapfile", "readarray", "getopts", "printf", "wait"):
                text = " ".join([w.text for w in cmd.words] + [
                    (rd.target.text if rd.target is not None else "") + (rd.hd.body if rd.hd is not None else "")
                    for rd in cmd.redirects])
                names = [w.value() for w in r.args if w.value() and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", w.value())]
                for n in names or ["REPLY", "MAPFILE"]:
                    self.defs.setdefault(n, []).append(("text", text))
        scripts = {id(s.script): s.script for s in sites}
        scripts[id(script)] = script
        for sc in scripts.values():
            for c in _consent_compounds(sc, sp):
                if c.kind in ("for", "select") and c.header and c.header[0].value():
                    name = c.header[0].value()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        for w in c.header[1:] or [None]:
                            self.defs.setdefault(name, []).append(("word", w) if w is not None else ("text", "$@"))
        # The working directories a relative path is read from: (path or None when computed, explicit?) - the call's
        # cwd, then each cd / pushd target in the command (explicit: the command itself names it).
        self.cwds = [(cwd, False)]
        for s in sites:
            r = sp.resolve(s.cmd)
            if r.name not in ("cd", "pushd"):
                continue
            args = [w for w in r.args if (w.value() or "") not in ("-L", "-P", "-e", "-@", "--")]
            if not args:
                self.cwds.append((self.home or "/", True))
                continue
            if args[0].value() == "-":
                continue
            toks = self.tokens(args[0])
            if any(o == "unk" for _, o in toks):
                self.cwds.append((None, True))
            elif any(o == "state" for _, o in toks) and all(t[0] == "c" for t, _ in toks):
                v = "".join(t[1] for t, _ in toks)
                self.cwds.extend([(os.path.join(c, v), True) for c, _ in self.cwds if c is not None] or [(v, True)])
            elif all(t[0] == "c" for t, _ in toks):
                v = "".join(t[1] for t, _ in toks)
                self.cwds.extend([(os.path.join(c, v), True) for c, _ in list(self.cwds) if c is not None])
            else:  # a glob: the directory it can match is the state dir only if the glob can match it
                self.cwds.append((self.state, True) if self.dir_state(toks) else (None, True))

    def _define(self, name, a):
        v = a.static_value()
        if v is not None:
            self.defs.setdefault(name, []).append(("static", v))
        elif a.value is not None:
            self.defs.setdefault(name, []).append(("word", a.value))
        else:
            self.defs.setdefault(name, []).append(("text", a.word.text))

    def marks_state(self, text):
        """Does computed source text (a substitution's body, a read's input) point at the state directory?"""
        text = text or ""
        if self.state in text or os.path.realpath(self.state) in text or "CLAUDE_STATE_DIR" in text:
            return True
        if self.state_is_tmp and re.search(r"/tmp\b|\bTE?MP(DIR)?\b|\bmktemp\b", text):
            return True
        if self.cwd_state(".") and re.search(r"\bpwd\b|\bO?L?D?PWD\b|\$\{?PWD|\bdirs\b", text):
            return True
        for name in re.findall(r"\$\{?!?([A-Za-z_][A-Za-z0-9_]*)", text):
            if self.var(name)[0] in ("state", "any"):
                return True
        return False

    def var(self, name):
        """("static", text) | ("state",) | ("unk",): what `$name` can hold as a directory."""
        if name in self._memo:
            return self._memo[name]
        if name in self._busy:
            return ("unk",)
        self._busy.add(name)
        try:
            out = self._var(name)
        finally:
            self._busy.discard(name)
        self._memo[name] = out
        return out

    def _var(self, name):
        defs = self.defs.get(name)
        if not defs:
            if name == "CLAUDE_STATE_DIR":
                return ("state",)
            if name in _CONSENT_TMP_VARS:
                return ("state",) if self.state_is_tmp else ("unk",)
            if name == "HOME" and self.home:
                return ("static", self.home)
            if name in ("PWD", "OLDPWD"):
                return ("state",) if self.cwd_state(".") else ("unk",)
            if name in _CONSENT_UNKNOWN:
                return ("any",)  # $_, BASH_REMATCH ...: any path the command touched, the flag's included
            if re.fullmatch(r"[0-9]+", name):
                return ("static", "")  # a positional parameter: the Bash tool's shell has none
            return ("unk",)
        statics, state = set(), False
        for d in defs:
            if d[0] == "static":
                statics.add(d[1])
            elif d[0] == "text":
                state = state or self.marks_state(d[1])
            else:
                toks = self.tokens(d[1])
                if any(o == "state" for _, o in toks) and not any(o == "unk" for _, o in toks):
                    if all(t[0] == "c" for t, _ in toks):
                        statics.add("".join(t[1] for t, _ in toks))
                    else:
                        state = state or bool(self.dir_state(toks))
                elif any(o == "glob" for _, o in toks):
                    state = state or bool(self.dir_state(toks))
                elif all(t[0] == "c" for t, _ in toks):
                    statics.add("".join(t[1] for t, _ in toks))
                elif any(p.kind in ("cmdsub", "backtick") and self.marks_state(p.text) for p in d[1].parts):
                    state = True
        if state or any(self.static_dir_state(v) for v in statics):
            return ("state",)
        if len(statics) == 1 and len(defs) == 1:
            return ("static", statics.pop())
        if statics and len(statics) == len(defs) and len(statics) <= 16:
            return ("multi", tuple(sorted(statics)))  # `for f in a b`: each value is tried
        return ("unk",)

    def static_dir_state(self, v):
        try:
            if v.startswith("/"):
                return _consent_same_dir(v, self.state)
            return any(c is not None and _consent_same_dir(os.path.join(c, v), self.state) for c, _ in self.cwds)
        except Exception:  # noqa: BLE001
            return True

    def tokens(self, word=None, text=None, choice=None):
        """A path word as [(token, origin)]: token ('c', ch) a literal character, ('?',) one character, ('*',) any run.

        A variable known here contributes its value (the state directory's path for one that can hold it); any other
        expansion reads as `*` (origin unk), a bracket class as one character, a brace as `*` (origin glob)."""
        out = []
        if word is None:
            return [(("c", ch), "lit") for ch in (text or "")]
        for k, p in enumerate(word.parts):
            if p.kind == "lit":
                out.extend((("c", ch), "lit") for ch in p.text)
            elif p.kind == "glob":
                t, i = p.text, 0
                while i < len(t):
                    if t[i] == "*":
                        out.append((("*",), "glob"))
                    elif t[i] == "?":
                        out.append((("?",), "glob"))
                    elif t[i] == "[":
                        j = t.find("]", i + 2)
                        if j < 0:
                            out.append((("c", "["), "lit"))
                        else:
                            out.append((("?",), "glob"))
                            i = j
                    else:
                        out.append((("c", t[i]), "lit"))
                    i += 1
            elif p.kind == "brace":
                out.append((("*",), "glob"))
            elif p.kind == "param":
                m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*|[0-9])", p.text or "")
                m2 = re.match(r"[#]?([A-Za-z_][A-Za-z0-9_]*)", p.text or "")
                if (p.text or "").startswith("!"):  # ${!V}: indirect, a value not known here that can be the state dir
                    out.append((("*",), "state"))
                    continue
                info = self.var((m or m2).group(1)) if (m or m2) else ("unk",)
                if info[0] == "multi" and m and choice and m.group(1) in choice:
                    info = ("static", choice[m.group(1)])
                if info[0] == "static" and m:
                    out.extend((("c", ch), "lit") for ch in info[1])
                elif info[0] == "any":
                    out.append((("*",), "state"))
                elif info[0] == "state":
                    if m or k == 0:
                        out.extend((("c", ch), "state") for ch in self.state)
                    else:
                        out.append((("*",), "state"))
                else:
                    out.append((("*",), "unk"))
            elif p.kind in ("cmdsub", "backtick", "procsub_in", "procsub_out") and self.marks_state(p.text):
                out.extend((("c", ch), "state") for ch in self.state)
            else:
                out.append((("*",), "unk"))
        if out and out[0][0] == ("c", "~") and (len(out) == 1 or out[1][0] == ("c", "/")) and self.home:
            out = [(("c", ch), "lit") for ch in self.home] + out[1:]
        return out

    def cwd_state(self, rel):
        """None, "cwd" (the call's own cwd is the state dir) or "explicit" (a cd in the command makes it so)."""
        hit = None
        for c, explicit in self.cwds:
            if c is None:
                if ".." in rel.split("/") and explicit:
                    return "explicit"
                continue
            if _consent_same_dir(os.path.join(c, rel), self.state):
                if explicit:
                    return "explicit"
                hit = "cwd"
        return hit

    def dir_state(self, dtoks):
        """None, "cwd" or "explicit": can the directory dtoks ([(token, origin)], None: no directory part) be the state
        dir? A directory with a value not known here is not, unless it climbs out with `..`."""
        if dtoks is None:
            return self.cwd_state(".")
        if any(o == "state" and t[0] != "c" for t, o in dtoks):
            return "explicit"
        lits = "".join(t[1] if t[0] == "c" else "\0" for t, _ in dtoks)
        if any(o == "unk" for _, o in dtoks):
            return "explicit" if ".." in lits.split("/") else None
        named = any(o == "state" for _, o in dtoks)
        if all(t[0] == "c" for t, _ in dtoks):
            d = lits or "/"
            if d.startswith("/"):
                return "explicit" if _consent_same_dir(d, self.state) else None
            hit = self.cwd_state(d)
            return "explicit" if hit and named else hit
        import fnmatch
        pat = "".join(("[" + t[1] + "]" if t[1] in "[]*?" else t[1]) if t[0] == "c" else t[0] for t, _ in dtoks)
        cands = {os.path.normpath(self.state), os.path.realpath(self.state)}
        if pat.startswith("/"):
            return "explicit" if any(fnmatch.fnmatchcase(s, os.path.normpath(pat)) for s in cands) else None
        hit = None
        for c, explicit in self.cwds:
            if c is None:
                continue
            if any(fnmatch.fnmatchcase(s, os.path.normpath(os.path.join(c, pat))) for s in cands):
                if explicit:
                    return "explicit"
                hit = "cwd"
        return hit

    @staticmethod
    def split(toks):
        cut = max((i for i, (t, _) in enumerate(toks) if t == ("c", "/")), default=-1)
        return toks[cut + 1:], (toks[:cut] if cut >= 0 else None)

    def target(self, word=None, text=None, named=False, toks=None):
        """Why writing the path word can create or change the consent flag, or None. A variable with a few known
        values (a for loop's) is tried with each. ``toks``: the path as tokens already (an option's attached value)."""
        if toks is not None:
            return self._target(None, None, named, None, toks)
        multi = {}
        for p in (word.parts if word is not None else ()):
            if p.kind == "param" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p.text or ""):
                info = self.var(p.text)
                if info[0] == "multi":
                    multi[p.text] = info[1]
        if multi:
            import itertools
            names = sorted(multi)
            for combo in itertools.islice(itertools.product(*(multi[n] for n in names)), 64):
                why = self._target(word, text, named, dict(zip(names, combo)))
                if why:
                    return why
            return None
        return self._target(word, text, named, None)

    def _target(self, word, text, named, choice, toks=None):
        toks = self.tokens(word, text, choice) if toks is None else list(toks)
        base, dtoks = self.split(toks)
        if CONSENT_TOKEN in "".join(t[1] for t, _ in base if t[0] == "c").lower():
            return "its target is named like the consent flag"
        if named and any(o in ("unk", "state") for _, o in toks):
            return "its target is computed in a command that names the consent flag"
        if not base or not _consent_name_may_match([t for t, _ in base]):
            return None
        where = self.dir_state(dtoks)
        if where is None:
            return None
        if any(o in ("unk", "state") and t[0] != "c" for t, o in base):
            return "its computed target can be the consent flag in the state directory"
        if where == "explicit":
            return "its target can match the consent flag in the state directory"
        # A glob reached only through the call's own cwd matches existing names alone (no new flag), and a literal
        # name that can be the flag's contains the stem (refused above).
        return None

    def into_dir(self, word=None, toks=None):
        """None, "cwd" or "explicit": can the directory word (a copy's destination) be the state dir? ``toks``: the
        directory as tokens already (an option's attached value)."""
        toks = self.tokens(word) if toks is None else list(toks)
        while len(toks) > 1 and toks[-1][0] == ("c", "/"):
            toks = toks[:-1]
        return self.dir_state(toks) if toks else None

    def source_may_be_flag(self, word, where):
        base, _ = self.split(self.tokens(word))
        if CONSENT_TOKEN in "".join(t[1] for t, _ in base if t[0] == "c").lower():
            return True
        if not base or not _consent_name_may_match([t for t, _ in base]):
            return False
        if any(o in ("unk", "state") and t[0] != "c" for t, o in base):
            return True  # a name not known here
        return where == "explicit"  # a glob: refused into an explicitly named state dir


def _consent_lead(view, w):
    """A word's tokens and its leading literal text: what an option parser can read before the first expansion."""
    toks = view.tokens(w)
    n = 0
    while n < len(toks) and toks[n][0][0] == "c" and toks[n][1] == "lit":
        n += 1
    return toks, "".join(t[1] for t, _ in toks[:n])


def _consent_text(toks):
    return "".join(t[1] if t[0] == "c" else "*" for t, _ in (toks or ()))


_CONSENT_SPECS = {}
# getopt tables (lib/shell_parse._spec: flags, then value-taking options) of the programs whose options this rule
# reads. A long option resolves by its GNU unique prefix (`--out` is `--output`); a short option takes its value
# attached (`-t<dir>`) or as the next word; an option not in the table is an error the caller fails closed on.
_CONSENT_SPEC_TEXT = {
    "sort": ("-b -d -f -g -i -M -h -n -R -r -V -c -C -m -s -u -z --ignore-leading-blanks --dictionary-order "
             "--ignore-case --general-numeric-sort --ignore-nonprinting --month-sort --human-numeric-sort "
             "--numeric-sort --random-sort --reverse --version-sort --check --debug --merge --stable --unique "
             "--zero-terminated --help --version",
             "-k -t -S -T -o --key --field-separator --buffer-size --temporary-directory --output --batch-size "
             "--compress-program --files0-from --parallel --random-source --sort"),
    "sed": ("-n -E -r -s -u -z -i --quiet --silent --debug --follow-symlinks --posix --regexp-extended --separate "
            "--sandbox --unbuffered --null-data --in-place --help --version",
            "-e -f -l --expression --file --line-length"),
    "cp": ("-a -b -d -f -i -H -l -L -n -P -p -R -r -s -T -u -v -x -Z --archive --attributes-only --backup "
           "--copy-contents --force --interactive --link --dereference --no-clobber --no-dereference --preserve "
           "--parents --recursive --reflink --remove-destination --strip-trailing-slashes --symbolic-link "
           "--no-target-directory --update --verbose --one-file-system --context --debug --keep-directory-symlink "
           "--help --version",
           "-S -t --suffix --target-directory --no-preserve --sparse"),
    "mv": ("-b -f -i -n -T -u -v -Z --backup --force --interactive --no-clobber --no-target-directory "
           "--strip-trailing-slashes --update --verbose --context --no-copy --exchange --debug --help --version",
           "-S -t --suffix --target-directory"),
    "ln": ("-b -d -F -f -i -L -n -P -r -s -T -v --backup --directory --force --interactive --logical "
           "--no-dereference --physical --relative --symbolic --no-target-directory --verbose --help --version",
           "-S -t --suffix --target-directory"),
    "install": ("-b -c -C -d -D -p -s -T -v -Z --backup --compare --directory --preserve-timestamps --strip "
                "--no-target-directory --verbose --preserve-context --context --debug --help --version",
                "-g -m -o -S -t --group --mode --owner --strip-program --suffix --target-directory"),
}


def _consent_spec(name):
    if name not in _CONSENT_SPECS and name in _CONSENT_SPEC_TEXT:
        from lib import shell_parse as sp
        bools, vals = _CONSENT_SPEC_TEXT[name]
        _CONSENT_SPECS[name] = sp._spec(bools.split(), vals.split())
    return _CONSENT_SPECS.get(name)


def _consent_opts(view, words, spec, permute=True):
    """GNU getopt reading of ``words`` against ``spec`` on the rule's path tokens, so a value with an expansion
    (`-t$CLAUDE_STATE_DIR`, `--output=$D/x`) is kept. Returns (opts, operands, error): opts is a list of (canonical
    option, value tokens or None, value Word when the value is a whole next word); error names the first option not
    in the table or computed (read as a flag)."""
    from lib import shell_parse as sp
    opts, operands, err = [], [], None
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        toks, lead = _consent_lead(view, w)
        whole = len(lead) == len(toks)
        if not lead.startswith("-") or (whole and lead == "-"):
            operands.append(w)
            i += 1
            if not permute:
                operands.extend(words[i:])
                break
            continue
        if whole and lead == "--":
            operands.extend(words[i + 1:])
            break
        nxt = words[i + 1] if i + 1 < n else None
        if lead.startswith("--"):
            name, eq, _ = lead.partition("=")
            res = sp._resolve_long(name, spec) if (eq or whole) else None
            if res is None:
                err = err or "option `%s` not known here" % name
                opts.append((name, toks[len(name) + 1:] if eq else None, None))
            elif eq:
                opts.append((res, toks[len(name) + 1:], None))
            elif res in spec["val"]:
                opts.append((res, view.tokens(nxt) if nxt is not None else None, nxt))
                i += 1
            else:
                opts.append((res, None, None))
            i += 1
            continue
        j, step = 1, 1
        while j < len(toks):
            if j >= len(lead):
                err = err or "a computed option"
                break
            ch = "-" + lead[j]
            if ch in spec["val"]:
                if j + 1 < len(toks):
                    opts.append((ch, toks[j + 1:], None))
                else:
                    opts.append((ch, view.tokens(nxt) if nxt is not None else None, nxt))
                    step = 2
                break
            if ch not in spec["bool"]:
                err = err or "option `%s` not known here" % ch
            opts.append((ch, None, None))
            j += 1
        if len(lead) == 1:
            err = err or "a computed option"
        i += step
    return opts, operands, err


def _consent_option_values(view, words):
    """For a program whose option table is not modelled here: every value an option word can carry (after `=`, or
    attached to a short option)."""
    for w in words:
        toks, lead = _consent_lead(view, w)
        if not lead.startswith("-") or len(toks) < 3:
            continue
        k = lead.find("=")
        if k >= 0:
            yield toks[k + 1:]
        elif not lead.startswith("--"):
            yield toks[2:]


# rsync's long flags that take no value: any other long option without `=` may take the next word as its value.
_CONSENT_RSYNC_FLAGS = frozenset({
    "--archive", "--verbose", "--recursive", "--relative", "--update", "--links", "--perms", "--times", "--group",
    "--owner", "--devices", "--specials", "--compress", "--checksum", "--delete", "--delete-after",
    "--delete-before", "--delete-during", "--delete-excluded", "--dry-run", "--progress", "--partial", "--inplace",
    "--stats", "--human-readable", "--quiet", "--hard-links", "--acls", "--xattrs", "--sparse", "--existing",
    "--ignore-existing", "--remove-source-files", "--itemize-changes", "--no-motd", "--force", "--numeric-ids",
    "--copy-links", "--safe-links", "--one-file-system", "--prune-empty-dirs", "--mkpath", "--append",
    "--append-verify", "--whole-file", "--no-whole-file", "--omit-dir-times", "--fuzzy", "--help", "--version"})


_CONSENT_RSYNC_INERT = frozenset({"--exclude", "--include", "--filter", "--temp-dir"})


def _consent_operands(view, r):
    """(sources, destination tokens or None for the cwd, destination is a directory?, recursive?, refusal or None)
    of a copy, move or link. cp, mv, ln and install are read with their getopt tables; rsync and link, whose tables
    are not modelled, fail closed: an option value that can be the state directory is refused."""
    args = list(r.args)
    spec = _consent_spec(r.name)
    if spec is not None:
        opts, ops, err = _consent_opts(view, args, spec)
        if err:
            for val in list(_consent_option_values(view, args)) + [view.tokens(w) for w in ops]:
                if val and view.into_dir(toks=val):
                    return ops, None, True, False, (f"`{r.name}` reads {err}, and an operand can be the state "
                                                     "directory")
        names = {o for o, _, _ in opts}
        no_dir = bool(names & {"-T", "--no-target-directory"}) or (
            r.name == "ln" and bool(names & {"-n", "--no-dereference"}))
        recursive = bool(names & {"-r", "-R", "-a", "--recursive", "--archive"})
        targets = [v for o, v, _ in opts if o in ("-t", "--target-directory")]
        if targets:
            return ops, targets[-1] or [], True, recursive, None
        if r.name == "ln" and len(ops) == 1:
            return ops, None, True, recursive, None
        if len(ops) < 2:
            return ops, None, False, recursive, None
        return ops[:-1], view.tokens(ops[-1]), not no_dir, recursive, None
    ops, value_next, odd, rest_ops = [], False, None, False
    for w in args:
        toks, lead = _consent_lead(view, w)
        if not rest_ops and lead.startswith("-") and not (lead == "-" and len(toks) == 1):
            if lead == "--" and len(toks) == 2:
                rest_ops = True
                continue
            # rsync's patterns (--exclude/--include/--filter, -f) and its temp dir (--temp-dir, -T: dot-named partial
            # files only) write nothing under their own name into the directory they name.
            inert = r.name == "rsync" and (lead.partition("=")[0] in _CONSENT_RSYNC_INERT or lead[:2] in ("-f", "-T"))
            for val in (() if inert else _consent_option_values(view, [w])):
                if val and view.into_dir(toks=val):
                    odd = f"an option of `{r.name}` names the state directory"
            value_next = (lead.startswith("--") and "=" not in lead and lead not in _CONSENT_RSYNC_FLAGS) or (
                not lead.startswith("--") and len(lead) == len(toks) and lead[-1:] in "efBT@M")
            value_next = "inert" if value_next and inert else value_next
            continue
        if value_next and value_next != "inert" and view.into_dir(w):
            odd = f"an option of `{r.name}` names the state directory"
        value_next = False
        ops.append(w)
    if odd:
        return ops, None, True, True, odd
    if r.name == "link":
        return ops[:-1], view.tokens(ops[-1]) if len(ops) >= 2 else None, False, False, None
    if len(ops) < 2:
        return ops, None, False, True, None
    return ops[:-1], view.tokens(ops[-1]), True, True, None


def _consent_unpack_dirs(view, r):
    """(extracts?, [destination tokens]) of an archive extraction; no destination: the cwd. Short option clusters,
    attached values (`-xC<dir>`), `--directory=<dir>`, its unique prefixes (`--dir`) and tar's old-style keys
    (`tar xfC a.tar <dir>`) are read."""
    args = list(r.args)
    name = _CONSENT_UNPACKERS.get(r.name, r.name)
    lex = [_consent_lead(view, w) for w in args]

    def value(i, toks, j):
        if j + 1 < len(toks):
            return toks[j + 1:], 0
        return (lex[i + 1][0] if i + 1 < len(lex) else []), 1

    if name == "tar":
        extracts, dests = False, []
        # GNU tar's -s is a flag, bsdtar's takes a pattern: both readings are taken.
        for vals in ("bCfFgHIKLNTVX", "bCfFgHIKLNsTVX"):
            i, pending = 0, []
            while i < len(lex):
                toks, lead = lex[i]
                if pending:
                    if pending.pop(0) == "C":
                        dests.append(toks)
                    i += 1
                    continue
                if i == 0 and lead and not lead.startswith("-"):
                    extracts = extracts or "x" in lead or len(lead) < len(toks)
                    pending = [ch for ch in lead if ch in vals]
                    i += 1
                    continue
                if lead == "--" and len(toks) == 2:
                    break
                if lead.startswith("--"):
                    opt, eq, _ = lead.partition("=")
                    if len(lead) < len(toks) and not eq:
                        extracts = True  # a computed long option
                    elif len(opt) >= 3 and "--directory".startswith(opt):
                        dests.append(toks[len(opt) + 1:] if eq else (lex[i + 1][0] if i + 1 < len(lex) else []))
                        i += 0 if eq else 1
                    elif len(opt) >= 3 and ("--extract".startswith(opt) or "--get".startswith(opt)):
                        extracts = True
                    i += 1
                    continue
                if lead.startswith("-") and len(toks) > 1:
                    j, skip = 1, 0
                    while j < len(toks):
                        if j >= len(lead):
                            extracts = True  # a computed option letter
                            break
                        ch = lead[j]
                        if ch == "x":
                            extracts = True
                        if ch in vals:
                            val, skip = value(i, toks, j)
                            if ch == "C":
                                dests.append(val)
                            break
                        j += 1
                    i += 1 + skip
                    continue
                i += 1
        return extracts, dests
    if name == "unzip":
        dests, i = [], 0
        while i < len(lex):
            toks, lead = lex[i]
            skip = 0
            if lead.startswith("-") and not lead.startswith("--"):
                for j in range(1, len(toks)):
                    ch = lead[j] if j < len(lead) else None
                    if ch in ("d", "P", "I", "O"):
                        val, skip = value(i, toks, j)
                        if ch == "d":
                            dests.append(val)
                        break
            i += 1 + skip
        return True, dests
    if name == "cpio":
        extracts, dests, i = False, [], 0
        while i < len(lex):
            toks, lead = lex[i]
            skip = 0
            if lead.startswith("--"):
                opt, eq, _ = lead.partition("=")
                if len(opt) >= 3 and "--directory".startswith(opt):
                    dests.append(toks[len(opt) + 1:] if eq else (lex[i + 1][0] if i + 1 < len(lex) else []))
                    skip = 0 if eq else 1
                elif len(opt) >= 3 and "--extract".startswith(opt):
                    extracts = True
            elif lead.startswith("-"):
                for j in range(1, len(toks)):
                    ch = lead[j] if j < len(lead) else None
                    if ch is None or ch == "i":
                        extracts = True
                    if ch in tuple("CDEFHIMOR"):
                        val, skip = value(i, toks, j)
                        if ch == "D":
                            dests.append(val)
                        break
            i += 1 + skip
        return extracts, dests
    here = [(("c", "."), "lit")]  # the cwd as a destination

    def long_is(lead, full, least=4):
        opt = lead.partition("=")[0]
        return len(opt) >= least and full.startswith(opt)

    def long_value(i, toks, lead):
        opt, eq, _ = lead.partition("=")
        return (toks[len(opt) + 1:], 0) if eq else ((lex[i + 1][0] if i + 1 < len(lex) else []), 1)

    if name == "gzip":
        # -N/--name restores the name stored in the file, next to the input (gzip strips its directory part).
        dec, keep_name, stdout, recursive = r.name in ("gunzip", "unpigz", "zcat"), False, r.name == "zcat", False
        if re.search(r"\bGZIP=", view.command) or "GZIP" in view.defs:
            keep_name = True  # options from the environment
        ops, i, rest = [], 0, False
        while i < len(lex):
            toks, lead = lex[i]
            skip = 0
            if rest or not lead.startswith("-") or (lead == "-" and len(toks) == 1):
                ops.append(toks)
            elif lead == "--" and len(toks) == 2:
                rest = True
            elif lead.startswith("--"):
                if len(lead) < len(toks) and "=" not in lead:
                    dec = keep_name = True  # a computed long option
                elif long_is(lead, "--name"):
                    keep_name = True
                elif long_is(lead, "--decompress") or long_is(lead, "--uncompress"):
                    dec = True
                elif long_is(lead, "--stdout", 5) or long_is(lead, "--to-stdout", 5):
                    stdout = True
                elif long_is(lead, "--recursive"):
                    recursive = True
                elif long_is(lead, "--suffix") and "=" not in lead:
                    skip = 1
            else:
                for j in range(1, len(toks)):
                    ch = lead[j] if j < len(lead) else None
                    if ch is None:
                        dec = keep_name = True  # a computed option letter
                        break
                    dec, keep_name = dec or ch == "d", keep_name or ch == "N"
                    stdout, recursive = stdout or ch == "c", recursive or ch == "r"
                    if ch == "S":
                        skip = 0 if j + 1 < len(toks) else 1
                        break
            i += 1 + skip
        if not (dec and keep_name and not stdout and ops):
            return False, []
        dests = []
        for toks in ops:
            _, dtoks = view.split(toks)
            dests.append(here if dtoks is None else dtoks)
            if recursive:
                dests.append(toks)
        return True, dests
    if name == "ar":
        # `ar x [--output <dir>] archive`: the key is the first word not a long option; members land in the cwd.
        key, dests, i = None, [], 0
        while i < len(lex):
            toks, lead = lex[i]
            skip = 0
            if lead.startswith("--"):
                if long_is(lead, "--output", 3):
                    val, skip = long_value(i, toks, lead)
                    dests.append(val)
                elif "=" not in lead and lead.partition("=")[0] in ("--plugin", "--target"):
                    skip = 1
            elif key is None:
                key = (toks, lead)
            i += 1 + skip
        extracts = key is not None and ("x" in key[1] or len(key[1]) < len(key[0]))
        return extracts, dests
    if name == "deb":
        # dpkg-deb -x/-X/-R/-e (dpkg -x/-X/-e) archive [dir]: every operand after the archive is a destination.
        letters = "xXe" if r.name == "dpkg" else "xXRe"
        longs = ("--extract", "--vextract", "--control") + (() if r.name == "dpkg" else ("--raw-extract",))
        extracts, ops = False, []
        for toks, lead in lex:
            if lead.startswith("--"):
                if (len(lead) < len(toks) and "=" not in lead) or any(long_is(lead, o, 5) for o in longs):
                    extracts = True
            elif lead.startswith("-") and len(toks) > 1:
                if len(lead) < len(toks) or any(ch in letters for ch in lead[1:]):
                    extracts = True
            else:
                ops.append(toks)
        return extracts, (ops[1:] or [here]) if extracts else []
    if name in ("pax", "rar", "lha", "unar"):
        # pax -r (into the cwd) and -rw (into the last operand); unrar/rar x|e archive [dir/] or -op<dir>; lha
        # x|e archive or xw=<dir>; unar -o/--output-directory <dir>. Every operand is tried as a destination too.
        extracts, dests, outdir, i, first = name == "unar", [], False, 0, True
        while i < len(lex):
            toks, lead = lex[i]
            skip = 0
            if name == "pax" and lead.startswith("-") and len(toks) > 1:
                extracts = extracts or "r" in lead[1:] or len(lead) < len(toks)
            elif name == "unar" and lead.startswith("-"):
                if lead in ("-o", "-output-directory") or long_is(lead, "--output-directory", 4):
                    val, skip = long_value(i, toks, lead) if lead.startswith("--") else (
                        (lex[i + 1][0] if i + 1 < len(lex) else []), 1)
                    dests.append(val)
                    outdir = True
            elif name == "rar" and lead.startswith("-op") and len(toks) > 3:
                dests.append(toks[3:])
                outdir = True
            elif name in ("rar", "lha") and first and not (name == "rar" and lead.startswith("-")):
                first = False
                k = lead.lstrip("-")
                extracts = len(lead) < len(toks) or (k[:1] in ("x", "e") if name == "rar" else bool(
                    set(k.split("w=")[0]) & {"x", "e"}))
                if name == "lha" and "w=" in lead:
                    dests.append(toks[lead.index("w=") + 2:])
                    outdir = True
            elif not lead.startswith("-"):
                dests.append(toks)
            i += 1 + skip
        return extracts, dests + ([] if outdir else [here])
    extracts = bool(lex) and lex[0][1] in ("x", "e")
    return extracts, [toks[2:] for toks, lead in lex if lead.startswith("-o") and len(toks) > 2]


# git commands that write nothing into their directory's work tree (object and ref housekeeping writes only under
# .git): with the state directory as their directory they pass; any other non-read git command there is refused.
# init, clone, checkout-index and worktree are read by _consent_git_tree itself.
_CONSENT_GIT_HERE_OK = frozenset({"fetch", "push", "remote", "config", "help", "version", "ls-remote",
                                  "branch", "tag", "var", "cat-file", "rev-list", "for-each-ref", "show-ref",
                                  "ls-tree", "gc", "fsck", "count-objects", "prune", "repack", "pack-refs"})


def _consent_git_tree(view, sp, r):
    """Why a git invocation can write files into the state directory, or None: its work tree (--work-tree,
    GIT_WORK_TREE, core.worktree by -c, --config-env, GIT_CONFIG_* or `git config`) can be the state directory, or it
    runs a command other than a read where the state directory is its directory (-C, cd, the call's cwd; a GIT_DIR
    or --git-dir without a work tree makes that directory the work tree)."""
    why = "it checks files out into the state directory"
    args = list(r.args)
    trees, cfg_trees, here, gitdirs, k = [], [], [], [], 0
    while k < len(args):
        toks, lead = _consent_lead(view, args[k])
        whole = len(lead) == len(toks)
        nxt = view.tokens(args[k + 1]) if k + 1 < len(args) else []
        opt, eq, _ = lead.partition("=")
        if whole and lead in sp.GIT_GLOBAL_VALUE_OPTS:
            val, k = nxt, k + 2
        elif eq and opt in sp.GIT_GLOBAL_VALUE_OPTS:
            val, k = toks[len(opt) + 1:], k + 1
        elif whole and lead in sp.GIT_GLOBAL_FLAGS:
            k += 1
            continue
        else:
            break
        if opt == "-C":
            here.append(val)
        elif opt == "--work-tree":
            trees.append(val)
        elif opt == "--git-dir":
            gitdirs.append(val)
        elif opt in ("-c", "--config-env"):
            m = 0
            while m < len(val) and val[m][0][0] == "c" and val[m][1] == "lit":
                m += 1
            vlead = "".join(t[1] for t, _ in val[:m])
            key, has_eq, _ = vlead.partition("=")
            if not has_eq or len(key) + 1 > len(val):
                if any(o in ("state", "unk") for _, o in val):
                    return why + " (a computed git config key)"
                continue
            if key.strip().lower() == "core.worktree":
                rest = val[len(key) + 1:]
                if opt == "--config-env":
                    info = view.var(_consent_text(rest)) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",
                                                                          _consent_text(rest)) else ("unk",)
                    if info[0] != "static":
                        return why + " (core.worktree from the environment)"
                    rest = view.tokens(text=info[1])
                cfg_trees.append(rest)
    sub = args[k].value() if k < len(args) else None
    for a in r.assignments:
        if a.name == "GIT_WORK_TREE":
            trees.append(view.tokens(a.value) if a.value is not None else [(("*",), "state")])
    if "GIT_WORK_TREE" in view.defs:
        info = view.var("GIT_WORK_TREE")
        if info[0] in ("state", "any"):
            return why
        trees.extend(view.tokens(text=v) for v in ((info[1],) if info[0] == "static" else
                                                    info[1] if info[0] == "multi" else ()))
    # The environment's config (GIT_CONFIG_COUNT/KEY_n/VALUE_n, GIT_CONFIG_PARAMETERS), set here or by export.
    env = {}
    for n in view.defs:
        if n.startswith("GIT_CONFIG_"):
            info = view.var(n)
            env[n] = info[1] if info[0] == "static" else None
    for a in r.assignments:
        if a.name.startswith("GIT_CONFIG_"):
            env[a.name] = a.static_value()
    pairs = []
    count = env.get("GIT_CONFIG_COUNT")
    if "GIT_CONFIG_COUNT" in env and not (count or "").isdigit():
        pairs.append((None, None))
    for n in range(min(int(count), 64) if (count or "").isdigit() else 0):
        pairs.append((env.get("GIT_CONFIG_KEY_%d" % n), env.get("GIT_CONFIG_VALUE_%d" % n)))
    if "GIT_CONFIG_PARAMETERS" in env:
        params = env["GIT_CONFIG_PARAMETERS"]
        if params is None:
            pairs.append((None, None))
        for item in sp.argv_split(params or ""):
            key, _eq, v = item.partition("=")
            pairs.append((key, v))
    for key, v in pairs:
        if key is None or key.strip().lower() == "core.worktree":
            if key is None and "worktree" not in view.command.lower():
                continue
            if v is None:
                return why + " (core.worktree from a computed environment)"
            cfg_trees.append(view.tokens(text=v))
    if sub == "config":
        rest = args[k + 1:]
        keyed = False
        for w in rest:
            v = w.value()
            if v is not None and v.lower() == "core.worktree":
                keyed = True
            elif v is None and any(p.kind not in ("lit", "glob") for p in w.parts) and "worktree" in w.text.lower():
                keyed = True
            elif keyed and not (v or "").startswith("-"):
                cfg_trees.append(view.tokens(w))
    # core.worktree is read relative to the git directory, which is not known here: a relative value that climbs out
    # with `..` can reach the state directory.
    for t in cfg_trees:
        text = _consent_text(t)
        if not text.startswith("/") and ".." in text.split("/") and not any(o == "state" for _, o in t):
            return why + " (a relative core.worktree)"
        trees.append(t)
    for t in trees:
        if t and view.into_dir(toks=t):
            return why
    slash = (("c", "/"), "lit")

    def at(d):
        """Can directory tokens d ([]: git's own directory) read from git's directory (-C, else the cwd) be the
        state directory?"""
        if d and (d[0][0] == ("c", "/") or d[0][1] in ("state", "unk") or any(o == "state" for _, o in d)):
            return view.into_dir(toks=d)
        if here:
            return any(h and view.into_dir(toks=list(h) + [slash] + list(d)) for h in here)
        return view.into_dir(toks=d) if d else view.cwd_state(".")

    rest = args[k + 1:] if sub is not None else []
    lexr = [_consent_lead(view, w) for w in rest]
    if sub in ("init", "clone"):
        # The new repository's directory, its git directory (GIT_DIR, --git-dir, --separate-git-dir) and every
        # operand: a template (--template, GIT_TEMPLATE_DIR, init.templateDir) copies files named in it there.
        for a in r.assignments:
            if a.name == "GIT_DIR":
                gitdirs.append(view.tokens(a.value) if a.value is not None else [(("*",), "state")])
        if "GIT_DIR" in view.defs:
            info = view.var("GIT_DIR")
            if info[0] in ("state", "any"):
                return f"it runs `git {sub}` with the state directory as its git directory"
            gitdirs.extend(view.tokens(text=v) for v in ((info[1],) if info[0] == "static" else
                                                         info[1] if info[0] == "multi" else ()))
        ops, j = [], 0
        while j < len(lexr):
            toks, lead = lexr[j]
            opt, eq, _ = lead.partition("=")
            if lead.startswith("--") and len(opt) >= 4 and "--separate-git-dir".startswith(opt):
                if eq:
                    gitdirs.append(toks[len(opt) + 1:])
                else:
                    gitdirs.append(lexr[j + 1][0] if j + 1 < len(lexr) else [])
                    j += 1
            elif lead.startswith("--") and len(lead) < len(toks) and not eq:
                return f"`git {sub}` reads a computed option"
            elif not lead.startswith("-") or (lead == "-" and len(toks) == 1):
                ops.append(toks)
            j += 1
        for d in gitdirs + ops:
            if d and at(d):
                return f"it runs `git {sub}` into the state directory"
        if sub == "init" and not ops and at([]):
            return "it runs `git init` with the state directory as its directory"
        return None
    if sub == "checkout-index":
        # --prefix (any unique abbreviation, `=` or the next word) is prepended to every path checked out: its
        # directory part is where the files land.
        prefixes, j = [], 0
        while j < len(lexr):
            toks, lead = lexr[j]
            opt, eq, _ = lead.partition("=")
            if lead == "--" and len(toks) == 2:
                break
            if lead.startswith("--") and len(opt) >= 3 and "--prefix".startswith(opt):
                if eq:
                    prefixes.append(toks[len(opt) + 1:])
                else:
                    prefixes.append(lexr[j + 1][0] if j + 1 < len(lexr) else [])
                    j += 1
            elif lead.startswith("--") and len(lead) < len(toks) and not eq:
                return "`git checkout-index` reads a computed option"
            j += 1
        if prefixes:
            for p in prefixes:
                base, dtoks = view.split(p)
                if dtoks is None:
                    dtoks = []
                elif not dtoks:
                    dtoks = [slash]  # the root
                if at(dtoks):
                    return "it checks files out under a --prefix in the state directory"
            return None
    if sub == "worktree":
        # `git worktree add <path>` checks out into <path>; the other actions write only under the git directory.
        if any(not lead.startswith("-") and at(toks) for toks, lead in lexr[1:]):
            return "it adds a git worktree in the state directory"
        return None
    if sub is not None and sub not in _CONSENT_GIT_READS and sub not in _CONSENT_GIT_HERE_OK:
        where = any(h and view.into_dir(toks=h) for h in here) if here else view.cwd_state(".")
        if where:
            return f"it runs `git {sub}` with the state directory as its directory"
    if sub is None and k < len(args):
        if any(h and view.into_dir(toks=h) for h in here) if here else view.cwd_state("."):
            return "it runs a computed git command with the state directory as its directory"
    return None


def _consent_git_config_file(view, t):
    """Can the write target be a git config file: `<dir>.git/config`, `.git/.../config(.worktree)`, `~/.gitconfig`,
    `git/config` (XDG), `config` written from inside a `.git` directory, or a file GIT_CONFIG* names?"""
    toks = view.tokens(t.word) if t.word is not None else view.tokens(text=t.path or "")
    text = _consent_text(toks)
    parts = text.split("/")
    base, parent = parts[-1], (parts[-2] if len(parts) > 1 else None)
    if base == ".gitconfig":
        return True
    if base in ("config", "config.worktree"):
        if parent is None:
            return any(c is None or re.search(r"\.git(/|$)", c) for c, _ in view.cwds)
        if parent.endswith(".git") or parent == "git" or "*" in parent or "/.git/" in "/" + text:
            return True
    named = [os.environ.get(n) for n in ("GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")]
    for n in ("GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        if n in view.defs:
            info = view.var(n)
            if info[0] != "static":
                return True
            named.append(info[1])
    try:
        return any(v and os.path.normpath(v) == os.path.normpath(text) for v in named)
    except ValueError:
        return True


def _consent_text_names_state(view, text):
    """Does command text name the state directory as a whole path (its literal path, $CLAUDE_STATE_DIR, a variable
    holding it, the cwd when that is it), or a core.worktree that climbs with `..`?"""
    text = text or ""
    for s in {view.state, os.path.realpath(view.state)}:
        if re.search(re.escape(s.rstrip("/") or "/") + r"/?\.?(?![\w.\-/])", text):
            return True
    if "CLAUDE_STATE_DIR" in text or re.search(r"(?i)worktree[^\n]*\.\.", text):
        return True
    if view.state_is_tmp and re.search(r"\$\{?(TMPDIR|TMP|TEMP|TEMPDIR|CLAUDE_TMPDIR)\b|\bmktemp\b", text):
        return True
    if view.cwd_state(".") and re.search(r"\bpwd\b|\$\{?O?L?D?PWD\b|\bdirs\b", text):
        return True
    for name in re.findall(r"\$\{?!?([A-Za-z_][A-Za-z0-9_]*)", text):
        if view.var(name)[0] in ("state", "any"):
            return True
    return False


def _consent_read_only(cmd, name, view, named_writes):
    """None when the simple command is one of the read-only shapes, else why not."""
    words = list(cmd.words[1:])
    vals = [w.value() for w in words]
    if name in _CONSENT_STRICT_ARGS and any(v is None and any(p.kind not in ("lit", "glob") for p in w.parts)
                                            for w, v in zip(words, vals)):
        return f"`{name}` takes a computed argument"
    vals = [v if v is not None else "" for v in vals]  # a glob operand: a file name, read only
    if name == "find" and any(v in _FIND_ACTIONS for v in vals):
        return "`find` runs or writes with an action"
    if name == "rg" and any(v and v.startswith("--pre") for v in vals):
        return "`rg --pre` runs a program"
    if name == "file" and any((v.startswith("-") and not v.startswith("--") and "C" in v[1:]) or (
            len(v.split("=")[0]) > 3 and "--compile".startswith(v.split("=")[0])) for v in vals):
        return "`file -C` writes a compiled magic file"
    if name == "printf" and any(v == "-v" or (v or "").startswith("-v") for v in vals[:1]):
        return "`printf -v` assigns a variable"
    if name == "sed":
        opts, operands, err = _consent_opts(view, words, _consent_spec("sed"))
        if any(o in ("-i", "--in-place", "-f", "--file") for o, _, _ in opts):
            return "`sed` edits in place or reads its script from a file"
        if err:
            return f"`sed` reads {err}"
        scripts = [_consent_text(v) for o, v, _ in opts if o in ("-e", "--expression")]
        if not scripts:
            scripts = [_consent_text(view.tokens(w)) for w in operands[:1]]
        for s in scripts:
            s = re.sub(r"\\.", "", s or "")
            s = re.sub(r"/[^/\n]*/", "", s)
            if re.search(r"[wWe]", s):
                return "a `sed` script can write a file or run a command"
        return None
    if name in ("awk", "gawk", "mawk", "nawk"):
        prog, skip = None, False
        for i, v in enumerate(vals):
            if skip:
                skip = False
                continue
            if v in ("-F", "-v", "--field-separator", "--assign"):
                skip = True
                continue
            if v.startswith("-F") or v.startswith("-v") or v.startswith("--field-separator=") or v.startswith(
                    "--assign="):
                continue
            if v == "--":
                continue
            if v.startswith("-"):
                return f"`{name} {v}` is not a read-only option"
            prog = v
            break
        if prog is None or re.search(r"[>|@]|system|\bclose\b|fflush|ENVIRON\[", prog):
            return f"an `{name}` program can write a file or run a command"
        return None
    if name == "sort":
        opts, _, err = _consent_opts(view, words, _consent_spec("sort"))
        if any(o == "--compress-program" for o, _, _ in opts):
            return "`sort --compress-program` runs a program"
        if err:
            return f"`sort` reads {err}"
        for o, v, w in opts:
            if o in ("-o", "--output") and v is not None:
                named_writes.append(w if w is not None else ("toks", v))
        return None
    if name == "tee":
        for w, v in zip(words, vals):
            if not (v or "").startswith("-") or v == "-":
                named_writes.append(w)
        return None
    if name == "git":
        i = 0
        while i < len(vals) and vals[i].startswith("-"):
            if vals[i] == "-C":
                i += 2
                continue
            if vals[i] in ("--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs", "--no-replace-objects"):
                i += 1
                continue
            return f"`git {vals[i]}` is not a read-only git option"
        sub = vals[i] if i < len(vals) else None
        opts = vals[i + 1:]
        if sub in _CONSENT_GIT_READS:
            # A long option and its unique prefixes (`--out`, `--open`), or git grep's -O in a cluster or with its
            # pager attached (`-O<cmd>`, `-iO<cmd>`).
            for v in opts:
                opt = v.split("=", 1)[0]
                if opt.startswith("--") and len(opt) > 2 and any(d.startswith(opt) or opt.startswith(d) for d in (
                        "--output", "--open-files-in-pager", "--ext-diff")):
                    return f"`git {sub} {v}` writes a file or runs a program"
                if v == "-O" or (sub == "grep" and v.startswith("-") and not v.startswith("--") and "O" in v[1:]):
                    return f"`git {sub} {v}` writes a file or runs a program"
            return None
        if sub == "commit":
            skip = False
            for v in opts:
                if skip:
                    skip = False
                    continue
                if v in ("-m", "--message"):
                    skip = True
                elif v.startswith("--message=") or (v.startswith("-m") and not v.startswith("--")):
                    continue
                elif v.startswith("-") and not v.startswith("--") and len(v) > 2 and set(v[1:-1]) <= set("aqsvn") \
                        and v[-1] == "m":
                    skip = True
                elif v.startswith("-") and v not in _CONSENT_GIT_COMMIT_OPTS:
                    return f"`git commit {v}` is not a plain commit"
            return None
        return f"`git {sub}` is not a read-only git command"
    return None


def _consent_uncommented(command, sp):
    out = list(command)
    try:
        sp._blank_comments(command, out)
    except Exception:  # noqa: BLE001 - the whole text, comments included
        return command
    return "".join(out)


def consent_flag_verdict(command, cwd, state):
    """None, or why the command can create, change, move, link, copy onto or delete the /do consent flag."""
    from lib import shell_parse as sp
    script = sp.parse(command)
    sites = list(_consent_sites(script, sp))
    named = CONSENT_TOKEN in _consent_norm(_consent_uncommented(command, sp)) or any(
        CONSENT_TOKEN in _consent_norm(w.value() or "") for s in sites for w in s.cmd.words)
    if named and script.error is not None:
        return "the command names the consent flag and cannot be parsed"
    view = _ConsentView(sp, script, sites, command, cwd, state)

    def deletes_state(t):
        if t.path:
            norm = os.path.normpath(t.path)
            return norm.startswith("/") and (_consent_same_dir(norm, state) or
                                             (one_slash(state) + "/").startswith(one_slash(norm) + "/"))
        if t.word is not None:
            toks = view.tokens(t.word)
            while len(toks) > 1 and toks[-1][0] == ("c", "/"):
                toks = toks[:-1]
            return bool(toks) and all(o == "state" or t2 == ("c", "/") for t2, o in toks) and any(
                o == "state" for _, o in toks)
        return False

    # 1. Every write target: redirections and the parser's write verbs.
    real_writes, config_writes = False, False
    for t in sp.write_targets(script):
        if t.mode == "delete" and deletes_state(t):
            return "it deletes or moves the state directory that holds the consent flag"
        if t.path is not None and (t.path in _CONSENT_DEVICES or t.path.startswith("/dev/fd/")):
            continue
        real_writes = True
        config_writes = config_writes or _consent_git_config_file(view, t)
        if t.word is not None:
            why = view.target(word=t.word, named=named)
        elif t.path is not None:
            why = view.target(text=t.path, named=named)
        else:
            why = "its target is computed" if named else None
        if why:
            return why
    # 1a. A git config file written by a command whose text names the state directory: a core.worktree there makes
    # the next checkout write the index's names into it. (A core.worktree already on disk is not seen here.)
    if config_writes and _consent_text_names_state(view, command):
        return "it writes a git config file with text that names the state directory (core.worktree)"
    for s in sites:
        r = sp.resolve(s.cmd)
        if r.name is None:
            continue
        # 2. Creators the write-target table does not list: each operand is a target.
        if r.name in _CONSENT_DIR_CREATORS:
            for w in r.args:
                if not (w.value() or "").startswith("-"):
                    why = view.target(word=w, named=named)
                    if why:
                        return why
        # 3. A copy, move or link into the state directory under a name that can be the flag's, or of the state
        # directory itself.
        if r.name in _CONSENT_COPIERS:
            sources, dest, dest_is_dir, recursive, odd = _consent_operands(view, r)
            if odd:
                return odd
            if r.name == "mv" and any(deletes_state(sp.WriteTarget(w.value(), "delete", "mv", word=w))
                                      for w in sources):
                return "it deletes or moves the state directory that holds the consent flag"
            where = view.cwd_state(".") if dest is None else view.into_dir(toks=dest)
            if where and not dest_is_dir:
                return "it replaces the state directory that holds the consent flag"
            if where and dest_is_dir:
                for w in sources:
                    v = w.value() or ""
                    if recursive and (v.endswith("/") or v.endswith("/.") or v == "."):
                        return "it copies a directory's contents, names not known here, into the state directory"
                    if view.source_may_be_flag(w, where):
                        return ("it copies, moves or links a file that can be named like the consent flag into the "
                                "state directory")
        # 3a. xargs, parallel and find -exec build their operands at run time: none may aim at the state directory.
        head = s.cmd.head().value() if s.cmd.words and s.cmd.head().value() else ""
        if "xargs" in [n for n, _ in r.wrappers] or sp.basename(head) in ("xargs", "parallel") or \
                "exec_argv" in s.context:
            if view.cwd_state(".") == "explicit":
                return "it runs a command with operands built at run time in the state directory"
            for w in list(s.cmd.words[1:]):
                _, dtoks = view.split(view.tokens(w))
                if (dtoks is not None and view.dir_state(dtoks) == "explicit") or view.into_dir(w) == "explicit":
                    return "it runs a command with operands built at run time in the state directory"
        # 3b. An archive extracted into the state directory writes names not known here.
        if r.name in _CONSENT_UNPACKERS:
            extracts, dests = _consent_unpack_dirs(view, r)
            if extracts and (any(view.into_dir(toks=d) == "explicit" for d in dests) if dests else
                             view.cwd_state(".") == "explicit"):
                return "it extracts an archive, whose names are not known here, into the state directory"
        # 3c. A git work tree in the state directory: a checkout writes names not known here.
        if r.name == "git":
            why = _consent_git_tree(view, sp, r)
            if why:
                return why
    if not named:
        return None
    # 4. The command names the flag: every simple command must be a read-only shape, and nothing it emits that
    # carries the name reaches a file.
    named_writes, emits = [], False
    for s in sites:
        cmd = s.cmd
        for red in cmd.redirects:
            body = (red.hd.body if red.hd is not None else None) or (
                red.target.text if red.op == "<<<" and red.target is not None else "")
            if CONSENT_TOKEN in _consent_norm(body):
                emits = True
        if not cmd.words:
            continue
        head = cmd.head().value()
        if s.dynamic or head is None:
            return "a command whose name is computed runs where the consent flag is named"
        name = sp.basename(head)
        if name not in _CONSENT_READ_ONLY:
            return f"`{name}` is not a read-only command, and the command names the consent flag"
        why = _consent_read_only(cmd, name, view, named_writes)
        if why:
            return why + ", and the command names the consent flag"
        if name in ("echo", "printf") and any(CONSENT_TOKEN in _consent_norm(w.text) for w in cmd.words[1:]):
            emits = True
    for w in named_writes:
        why = (view.target(toks=w[1], named=True) if isinstance(w, tuple) else
               view.target(text=w, named=True) if isinstance(w, str) else view.target(word=w, named=True))
        if why:
            return why
        real_writes = True
    if emits and real_writes:
        return "it writes text that names the consent flag into a file"
    return None


def consent_flag_rule(command, payload):
    """The /do consent flag is written only by hooks/prompt-workflow.py when the owner types /do; no Bash call
    writes, creates, moves, links, copies onto or deletes it. Runs before the /do and /allow releases."""
    ti = payload.get("tool_input") if isinstance(payload, dict) else None
    cwd = (ti.get("cwd") if isinstance(ti, dict) else None) or (payload.get("cwd") if isinstance(payload, dict) else
                                                                 None) or os.getcwd()
    state = state_dir()
    try:
        why = consent_flag_verdict(command, str(cwd), state)
    except Exception:  # noqa: BLE001 - an analysis that cannot finish refuses a command that names the flag
        why = "the consent-flag check could not read the command" if (
            CONSENT_TOKEN in _consent_norm(command) or "CLAUDE_STATE_DIR" in command) else None
    if why:
        refuse("BLOCKED: do-consent-flag-write — this command can write, create, move, link, copy onto or delete the "
               "/do consent flag", f"Command: {command}",
               f"REASON: {why}. The flag <state dir>/{CONSENT_PREFIX}<session id>{CONSENT_SUFFIX} is written only by "
               "hooks/prompt-workflow.py when the owner types /do; a Bash-written one would grant /do consent the "
               "owner never gave. Reading it (cat, ls, grep, sed -n, awk, git log ...) is allowed; once a command "
               "names the flag, every program in it must be one of those read-only shapes. Neither /do nor /allow "
               "releases this rule.")


# ── Bulk-commit sentinel (BS-17) ─────────────────────────────────────────────

BULK_NAMES = ("claude-bulk-commit-sentinel-", "write-bulk-commit-sentinel.py", "userprompt-bulk-commit-capability.py")


def _active_substitution(text):
    """True when $( <( >( or ` is live: unquoted, or $( and ` inside "..". '..' and $'..' bodies are inert."""
    unq, single, double, ansi = 0, 1, 2, 3
    state, i, n = unq, 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == unq:
            if c == "$" and nxt == "'":
                state, i = ansi, i + 2
                continue
            if (c in "$<>" and nxt == "(") or c == "`":
                return True
            if c in "'\"":
                state = single if c == "'" else double
            elif c == "\\" and nxt:
                i += 1
            i += 1
        elif state == single:
            state = unq if c == "'" else single
            i += 1
        elif state == double:
            if c == "\\" and nxt:
                i += 2
                continue
            if (c == "$" and nxt == "(") or c == "`":
                return True
            state = unq if c == '"' else double
            i += 1
        else:
            if c == "\\" and nxt:
                i += 2
                continue
            state = unq if c == "'" else ansi
            i += 1
    return False


def _ansi_decode(s):
    escapes = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'b': '\b', 'f': '\f', 'v': '\v', '\\': '\\', "'": "'", '"': '"'}

    def repl(m):
        g = m.group(0)
        if g[1] in 'xUu01234567':
            return chr(int(g[2:], 16)) if g[1] in 'xUu' else chr(int(g[2:] if g[1] == '0' else g[1:], 8))
        return escapes.get(g[1], g)
    try:
        return re.sub(r'\\(?:x[0-9a-fA-F]{2}|U[0-9a-fA-F]{8}|u[0-9a-fA-F]{4}|0[0-7]{1,3}|[0-7]{1,3}|[ntrabfv\\\'"])', repl, s)
    except Exception:  # noqa: BLE001
        return None


def bulk_sentinel_decision(cmd):
    """PURE_READ, DENY or TOKENIZER_ERROR for a command naming the bulk-commit sentinel or its writers.

    Only one bare read of the protected path passes (one of ls stat cat file wc head tail grep jq find test [, or
    git): no separator, newline, substitution, recursive shell, eval/source, leading assignment, keyword, xargs,
    redirection, tee, or find write action (its ANSI-C spellings decoded). The sentinel is minted only by the
    userprompt-bulk-commit-capability hook, never from Bash. A name that appears only inside a longer argument is
    text, not a reference.
    """
    import shlex
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.commenters = ''
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        return 'TOKENIZER_ERROR'
    if '\n' in cmd or _active_substitution(cmd):
        return 'DENY'
    compound = {';', '&&', '||', '|', '&', '|&', ';;'}
    if any(t in compound for t in tokens):
        return 'DENY'
    shells = {'bash', 'sh', 'zsh', 'dash', 'python', 'python3', 'node', 'perl', 'ruby'}
    for i, t in enumerate(tokens[:-1]):
        nxt = tokens[i + 1]
        if t in shells and (nxt in ('-c', '-e') or (nxt.startswith('-') and re.match(r'^-[a-zA-Z]*[ce][a-zA-Z]*$', nxt))):
            return 'DENY'
    if any(t in ('eval', 'source', '.') and (i == 0 or tokens[i - 1] in compound) for i, t in enumerate(tokens)):
        return 'DENY'
    if tokens and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[0]):
        return 'DENY'
    keywords = {'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac', 'function', 'select'}
    redirects = {'>', '>>', '<', '<>', '>|', '&>', '&>>', '>&', '<&', '<<', '<<-', '<<<'}
    if any(t in keywords or t in redirects for t in tokens) or 'xargs' in tokens or 'tee' in tokens:
        return 'DENY'
    actions = {'-exec', '-execdir', '-delete', '-ok', '-okdir', '-fprint', '-fprint0', '-fprintf', '-fls'}
    for t in tokens:
        decoded = _ansi_decode(t.replace('$', ''))
        if t in actions or t.replace('$', '') in actions or decoded is None or decoded in actions:
            return 'DENY'
    standalone = in_arg = False
    for t in tokens:
        for script in BULK_NAMES[1:]:
            if t == script or t.endswith('/' + script):
                standalone = True
            elif script in t:
                in_arg = True
        if t.rsplit('/', 1)[-1].startswith(BULK_NAMES[0]) and not any(c in t for c in ' \t\n'):
            standalone = True
        elif BULK_NAMES[0] in t:
            in_arg = True
    if in_arg and not standalone:
        return 'PURE_READ'
    if tokens and tokens[0] in ('git', 'ls', 'stat', 'cat', 'file', 'wc', 'head', 'tail', 'grep', 'jq', 'find', 'test', '['):
        return 'PURE_READ'
    return 'DENY'


def bulk_sentinel_rule(command):
    if not any(name in command for name in BULK_NAMES):
        return
    decision = bulk_sentinel_decision(command)
    if decision == 'TOKENIZER_ERROR':
        refuse("BLOCKED: bulk-commit-sentinel-write — the command could not be tokenized (likely an unterminated "
               "quote), so it is refused (fail-closed)", f"Command: {command}", released_line())
    elif decision != 'PURE_READ':
        refuse("BLOCKED: bulk-commit-sentinel-write — Bash command references the protected bulk sentinel path or a "
               "sentinel-writer script (write-bulk-commit-sentinel.py) in a compound, write or run context — refused",
               f"Command: {command}",
               "REASON: the bulk-commit sentinel is minted only by the userprompt-bulk-commit-capability hook, never "
               "from Bash. Only one bare 'ls|stat|cat|file|wc|head|tail|grep|jq|find|test|[' (or git) invocation "
               "of the path, with no separator, substitution, recursive shell, redirection, tee, xargs or find write "
               "action, passes.", released_line())


# ── Hard-banned scripts (BS-19) ──────────────────────────────────────────────

_HB_CMD = (r"""(^|[;&|(`{!]|\$\()\s*(([^\s;&|]*/)?(sudo|env|nohup|exec|command|time|nice|timeout|setsid|xargs|source|\.|"""
           r"""(ba|z|da|k)?sh|if|then|do|else|while|until|[-<]\S*|[0-9]\S*|[A-Za-z_][A-Za-z0-9_]*=\S*)\s+)*["']?([^\s;&|]*/)?""")
_HB_RUNS_TEXT = re.compile(
    r"(^|[\s;&|()`])((\S*/)?((ba|z|da|k|c|tc|fi|r)?sh|eval|ssh|watch|trap|su|parallel|tmux|screen|alias|flock|script|xargs"
    r"|source|exec|[gmn]?awk|perl|ruby|python[\d.]*|node|php|lua|tclsh|expect|sed|n?vim?|make))"
    r"(?=$|[\s;&|()`])|(^|[;&|()`])\s*\.\s")


def executable_view_or_raw(command):
    """lib/shell_parse.py's executable view of the command; the raw command when the parser is unavailable."""
    try:
        from lib.shell_parse import executable_view
        return executable_view(command)
    except Exception:  # noqa: BLE001
        return command


_HB_NOEXEC_SHELLS = frozenset({"bash", "sh", "dash"})
_HB_SHELL_LONG = frozenset({"--norc", "--noprofile", "--noediting", "--posix", "--restricted", "--verbose", "--login"})
# The command word of a shell read as inert: written bare, or as an absolute path in a system bin directory.
_HB_SHELL_WORD = re.compile(r"(/bin/|/usr/bin/|/usr/local/bin/)?(bash|sh|dash)")
_HB_TEST_WORD = re.compile(r"test|\[")
_HB_PLAIN_WORD = re.compile(r"echo|printf|true|false|:")
# Options an inert noexec shell may carry: none of them runs, echoes or sources anything.
_HB_INERT_LONG = frozenset({"--norc", "--noprofile", "--noediting", "--posix", "--restricted"})
_HB_INERT_FLAGS = frozenset("nxeuc")
_HB_INERT_SET = frozenset({"noexec", "errexit", "nounset", "xtrace", "pipefail", "posix"})
# Unary file-test operators: bash reads their operand as a file name only.
_HB_FILE_TESTS = frozenset({"-e", "-f", "-d", "-r", "-w", "-x", "-s", "-L", "-h", "-b", "-c", "-p", "-S", "-g",
                            "-u", "-k", "-O", "-G", "-N", "-a"})
_HB_DEFAULT_NAMES = re.compile(r"session-recovery|restart-all-sessions")


def _hb_shell_options(args):
    """A bash/sh/dash argument list read as the shell reads it: (runs, has_c, has_s, operands, verbose). runs is
    False when the options leave noexec on (`-n`, `-nx`, `-o noexec`; the last one wins, `+n` / `+o noexec` turn it
    off), so the shell reads its script or `-c` string without running it; an interactive (`-i`) shell, which
    ignores noexec, runs. verbose is True when any `-v`, `-o verbose` or `--verbose` appears (the shell then echoes
    the script it reads). None for an option it cannot read."""
    noexec = interactive = has_c = has_s = verbose = False
    k = 0
    while k < len(args):
        v = args[k].value()
        if v is None:
            return None
        if v in ("--", "-"):
            k += 1
            break
        if v.startswith("--"):
            if v in ("--rcfile", "--init-file"):
                k += 2
            elif v in _HB_SHELL_LONG:
                verbose = verbose or v == "--verbose"
                k += 1
            else:
                return None
            continue
        if len(v) < 2 or v[0] not in "-+":
            break
        k += 1
        for ch in v[1:]:
            if ch in "oO":
                if k >= len(args) or args[k].value() is None:
                    return None
                if ch == "o" and args[k].value() == "noexec":
                    noexec = v[0] == "-"
                verbose = verbose or (ch == "o" and args[k].value() == "verbose")
                k += 1
            elif ch == "n":
                noexec = v[0] == "-"
            elif ch == "v":
                verbose = True
            elif v[0] == "-" and ch in "ics":
                interactive = interactive or ch == "i"
                has_c = has_c or ch == "c"
                has_s = has_s or ch == "s"
    return (interactive or not noexec), has_c, has_s, args[k:], verbose


def hard_ban_run_lines(command):
    """Lines naming what each bash/sh/dash in command runs, found through lib/shell_parse.py at command position
    (wrappers peeled, substitutions descended): `bash <script>`, or its `-c` string, for a shell that runs, and
    `bash <script>` for a verbose noexec one (its echo of the script can be carried on). Appended to the text the
    default hard ban reads, so an option the command-word pattern does not read (`bash +x x.sh`,
    `bash -o errexit x.sh`, `bash -n +n x.sh`) still shows the run. Empty when command does not parse."""
    try:
        from lib.shell_parse import Compound, SimpleCommand, active_parts, parse, resolve
    except Exception:  # noqa: BLE001
        return ""
    script = parse(command)
    if script.error is not None:
        return ""
    runs_text = []

    def nested(words):
        for w in words:
            for p in active_parts(w.parts):
                if p.body is not None:
                    visit(p.body)

    def visit_cmd(cmd):
        if isinstance(cmd, Compound):
            nested(cmd.header)
            nested([r.target for r in cmd.redirects if r.target is not None])
            for body in cmd.body:
                visit(body)
            return
        if not isinstance(cmd, SimpleCommand):
            return
        res = resolve(cmd)
        if res.unresolved is None and res.head is not None and res.name in _HB_NOEXEC_SHELLS:
            opts = _hb_shell_options(list(res.args))
            if opts is not None:
                runs, has_c, has_s, operands, verbose = opts
                if not runs and verbose and operands and not has_c and operands[0].value() is not None:
                    runs_text.append("bash " + operands[0].value())
                elif runs and operands and (has_c or not has_s) and operands[0].value() is not None:
                    runs_text.append(operands[0].value() if has_c else "bash " + operands[0].value())
        nested([a.word for a in cmd.assignments] + list(cmd.words) +
               [r.target for r in cmd.redirects if r.target is not None])

    def visit(s):
        for pl, _sep in s.items:
            for stage in pl.stages:
                visit_cmd(stage)

    visit(script)
    return "".join("\n" + line for line in runs_text)


def _hb_plain(w):
    """True for a word that is one plain literal: no expansion, substitution, glob, brace or ANSI-C part."""
    return w is not None and w.literal() is not None and all(p.kind == "lit" for p in w.parts)


def _hb_bare(w, rx):
    """True for a word written bare (no quote, no escape) whose text matches rx whole."""
    return _hb_plain(w) and not w.quoted() and "\\" not in w.text and rx.fullmatch(w.text) is not None


def _hb_inert_redirect(r):
    """True for a redirection that only discards or duplicates: a dup or close, or /dev/null."""
    if r.hd is not None or r.heredoc is not None or r.fd_var is not None:
        return False
    if r.op in (">&", "<&"):
        return r.dup is not None or r.close
    return r.op in ("<", ">", ">>") and _hb_plain(r.target) and r.target.literal() == "/dev/null"


def _hb_inert_shell(words):
    """True for the arguments of a bash/sh/dash that leaves noexec on and neither echoes, sources nor runs
    anything: only `-`/`+` clusters of n x e u c, `-o`/`+o` with a harmless set option, a harmless long option,
    `--`, then operands; noexec on at the end (the last of -n/+n/-o noexec/+o noexec wins); every word a plain
    literal."""
    if not all(_hb_plain(w) for w in words):
        return False
    vals = [w.literal() for w in words]
    noexec = False
    k = 0
    while k < len(vals):
        v = vals[k]
        if v == "--":
            break
        if v.startswith("--"):
            if v not in _HB_INERT_LONG:
                return False
            k += 1
            continue
        if len(v) < 2 or v[0] not in "-+":
            break
        k += 1
        for ch in v[1:]:
            if ch == "o":
                if k >= len(vals) or vals[k] not in _HB_INERT_SET:
                    return False
                if vals[k] == "noexec":
                    noexec = v[0] == "-"
                k += 1
            elif ch == "n":
                noexec = v[0] == "-"
            elif ch not in _HB_INERT_FLAGS:
                return False
    return noexec


def _hb_inert_test(words, closer):
    """True for one unary file test, `[!] -f FILE` (then closer, when given), every word a plain literal."""
    if not all(_hb_plain(w) for w in words):
        return False
    vals = [w.literal() for w in words]
    if closer is not None:
        if not vals or vals[-1] != closer:
            return False
        vals = vals[:-1]
    if vals[:1] == ["!"]:
        vals = vals[1:]
    return len(vals) == 2 and vals[0] in _HB_FILE_TESTS


def hard_ban_inert_shape(command):
    """True when the whole command only syntax-checks, tests for or prints and runs nothing else: it parses cleanly
    into a list joined by `&&`, `||` or `;` (no pipe, background or newline) of single commands, each one of
      (a) a noexec, non-verbose bash/sh/dash whose command word is written bare or as a /bin, /usr/bin or
          /usr/local/bin path (`bash -n x.sh`), with only harmless options and plain literal words;
      (b) one unary file test in `test`, `[` or `[[ ]]`, optionally negated (`[[ ! -f x.sh ]]`), plain literals;
      (c) echo, printf (no option), true, false or `:` with plain literal words naming no default banned script;
    with no assignment, substitution, expansion, function, alias, here-doc or process substitution anywhere and
    no redirection but a dup or /dev/null. Anything else (cat, tr, grep, eval, a wrapper, a relative or quoted
    shell word, ...) is not this shape, and the hard ban reads the raw command as it always has."""
    try:
        from lib.shell_parse import Compound, SimpleCommand, parse
    except Exception:  # noqa: BLE001
        return False
    script = parse(command)
    if script.error is not None or script.errors() or not script.items:
        return False
    for pl, sep in script.items:
        if sep not in ("&&", "||", ";", "") or len(pl.stages) != 1 or pl.timed or pl.pipes:
            return False
        cmd = pl.stages[0]
        if isinstance(cmd, Compound):
            if cmd.kind != "cond" or cmd.body or not all(_hb_inert_redirect(r) for r in cmd.redirects):
                return False
            if not _hb_inert_test(list(cmd.header), None):
                return False
            # the header keeps words only: what lies between `[[` and `]]` must be exactly those words
            rest = command[cmd.span[0]:cmd.span[1]]
            for w in cmd.header:
                i = rest.find(w.text)
                if i < 0:
                    return False
                rest = rest[:i] + " " + rest[i + len(w.text):]
            if re.fullmatch(r"\[\[[ \t]+\]\]", rest.strip()) is None:
                return False
            continue
        if not isinstance(cmd, SimpleCommand) or cmd.assignments or cmd.negated or cmd.timed or not cmd.words:
            return False
        if not all(_hb_inert_redirect(r) for r in cmd.redirects):
            return False
        head, args = cmd.words[0], list(cmd.words[1:])
        if _hb_bare(head, _HB_SHELL_WORD):
            if not _hb_inert_shell(args):
                return False
        elif _hb_bare(head, _HB_TEST_WORD):
            if not _hb_inert_test(args, "]" if head.text == "[" else None):
                return False
        elif _hb_bare(head, _HB_PLAIN_WORD):
            if not all(_hb_plain(w) and not _HB_DEFAULT_NAMES.search(w.literal()) for w in args):
                return False
            if head.text == "printf" and args and args[0].literal().startswith("-"):
                return False
        else:
            return False
    return True


def hard_ban_mask(t):
    """t with ; & | ( ! { inside quoted data made inert, unless a word outside quotes may run text; t when unsure."""
    n, i, o, u = len(t), 0, [], []

    def code(j):  # end of the $( or ` code at j inside "..", or -1 when a quote inside makes it unsure
        k = j + 1 if t[j] == "`" else j + 2
        d = 1
        while k < n and d:
            if t[k] in "'\"\\":
                return -1
            d += (t[k] == "(") - (t[k] == ")") if t[j] == "$" else -(t[k] == "`")
            k += 1
        return k if not d else -1
    while i < n and o is not None:
        c = t[i]
        q = '"' if c == '"' else "'"
        if c == "\\":
            u.append(t[i:i + 2])
            o.append(t[i:i + 2])
            i += 2
            continue
        if c not in "'\"" and not t.startswith("$'", i):
            u.append(c)
            o.append(c)
            i += 1
            continue
        j = i + 1 + (c == "$")
        b = [t[i:j]]
        while j < n and t[j] != q:
            if t[j] == "\\" and c != "'":
                b.append(t[j:j + 2])
                j += 2
                continue
            k = code(j) if c == '"' and (t.startswith("$(", j) or t[j] == "`") else j
            if k < 0:
                o = None
                break
            if k > j:
                b.append(t[j:k])
                j = k
                continue
            b.append("_" if t[j] in ";&|(!{" else t[j])
            j += 1
        if o is None or j >= n:
            o = None
            break
        o.append("".join(b) + q)
        u.append(" ")
        i = j + 1
    return t if o is None or _HB_RUNS_TEXT.search("".join(u)) else "".join(o)


def hard_ban_rule(command):
    """Scripts that manage session state or restart daemons. A set CLAUDE_HARD_BANNED_SCRIPTS is '|'-separated EREs,
    each matched anywhere; unset, session-recovery and restart-all-sessions match only as the command word: in the
    text with its quoted data masked (unless a word outside quotes names a program that runs text), or in the
    parser's executable view, which keeps what a shell `-c`, a git alias or a substitution runs and blanks the data
    an option such as git's `-c` merely configures. The default names pass a whole command of hard_ban_inert_shape
    (`bash -n x.sh`, `[[ ! -f x.sh ]] && echo missing`); any other command is read raw, with the lines of
    hard_ban_run_lines appended."""
    configured = os.environ.get("CLAUDE_HARD_BANNED_SCRIPTS", "")
    value = (configured or "session-recovery|restart-all-sessions").split("\n", 1)[0]
    bans = value.split("|")
    if bans and bans[-1] == "":
        bans.pop()
    data = None
    view = None
    text = command
    if not configured:
        try:
            if hard_ban_inert_shape(command):
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            text = command + hard_ban_run_lines(command)
        except Exception:  # noqa: BLE001
            text = command
    for ban in bans:
        if configured:
            rx = ban
        else:
            rx = _HB_CMD + ban + r"""(\.sh)?(["'\s;&|)<>`]|$)"""
            if data is None and grep(rx, text):
                try:
                    masked = hard_ban_mask(text).rstrip("\n")
                except Exception:  # noqa: BLE001
                    masked = ""
                data = masked or text
        if ban and not configured and view is None:
            view = executable_view_or_raw(text)
        if ban and (grep(rx, data if data is not None else text) or (not configured and grep(rx, view))):
            refuse(f"BLOCKED: hard-banned script '{ban}' is refused", f"Command: {command}",
                       "REASON: it manages session state or restarts daemons and can kill all sessions. Only the user "
                       "runs it manually.", released_line())


# ── Local service, disk and process rules ────────────────────────────────────

def _subcommands(command):
    return command.replace("&&", "\n").replace("||", "\n").replace(";", "\n").split("\n")


SENSITIVE_NAME = re.compile(r"\.env|credentials|secret|password")


def sensitive_redirect(command):
    """'write' when a command redirects its output into a file named like a secret, 'redirect' when a command that
    names such a file (an argument or an input redirection) writes its output to a file; None otherwise.

    Read from lib/shell_parse.py's commands, so a name inside quoted data is not a redirection. A command the parser
    cannot read is judged on its raw text.
    """
    try:
        from lib.shell_parse import parse, walk
        script = parse(command)
        if script.error is not None:
            raise ValueError(script.error.code)
        for site in walk(script):
            redirs = [r for r in site.cmd.redirects if r.target is not None]
            outputs = [r for r in redirs if r.writes()]
            if any(SENSITIVE_NAME.search(r.target.text) for r in outputs):
                return "write"
            if outputs and (any(SENSITIVE_NAME.search(w.text) for w in site.cmd.words[1:])
                            or any(SENSITIVE_NAME.search(r.target.text) for r in redirs if not r.writes())):
                return "redirect"
        return None
    except Exception:  # noqa: BLE001
        if grep(r"(>|>>)\s*\S*(\.env|credentials|secret|password)", command):
            return "write"
        if grep(r"(\.env|credentials|secret|password)\S*\s*(>|>>)", command):
            return "redirect"
        return None


def all_targets_whitelisted(command, verb_re, whitelist, strip_service=False):
    """False when a systemctl target in any && || ; part of the command is not on the whitelist."""
    allowed = whitelist.split()
    for sub in _subcommands(command):
        if not re.search(verb_re + r"\s", sub):
            continue
        args = re.sub(r".*" + verb_re + r"\s+", "", sub, count=1)
        for arg in args.split():
            if arg.startswith("-"):
                continue
            if (arg[:-8] if strip_service and arg.endswith(".service") else arg) not in allowed:
                return False
    return True


def service_rules(command, view, env):
    """BS-20/21, BS-23, BS-25..BS-31: secrets, docker, disks, kills, units, workflow state (`view`: executable view)."""
    family = env["family"]
    sensitive = sensitive_redirect(command)
    if sensitive == "write":
        refuse("BLOCKED: Attempting to write to sensitive file via Bash", f"Command: {command}",
               "Edit sensitive files manually — never via AI-driven Bash redirection.", released_line())
    elif sensitive == "redirect":
        refuse("BLOCKED: Attempting to redirect from/to sensitive file via Bash", f"Command: {command}",
               "Edit sensitive files manually — never via AI-driven Bash redirection.", released_line())
    if grep(r"(>|>>|tee|cp|mv|sed|awk)\s.*/etc/docker/daemon\.json", command):
        refuse("BLOCKED: Modifying Docker daemon config is refused", f"Command: {command}", released_line())
    if grep(r"docker.compose\s+(down|restart|stop)", command):
        refuse("BLOCKED: docker-compose down/stop/restart is refused", f"Command: {command}", released_line())
    if grep(r"docker\s+system\s+prune\s+-a", command):
        refuse("BLOCKED: docker system prune -a is refused", f"Command: {command}", released_line())
    if grep(r"^\s*(dd|mkfs|fdisk|shred)\b", view):
        refuse("BLOCKED: Destructive disk operation detected", f"Command: {command}", released_line())
    if grep(r"(killall|pkill)\s+.*(" + (re.escape(family) + "|" if family else "") + "claude|docker)", view):
        refuse(f"BLOCKED: Killing {family + '/' if family else ''}claude/docker processes is refused",
                   f"Command: {command}", released_line())
    if grep(r"(^|[ \t;|&])(kill)[ \t]+-", view):
        refuse("BLOCKED: kill with signals is refused — use graceful shutdown methods", f"Command: {command}",
                   released_line())
    prefix = env["prefix"]
    if grep(r"systemctl\s+" + DAEMON_VERBS + r"(\s+|\b)", command) \
            and (not prefix or not grep(re.escape(prefix), command)) \
            and not all_targets_whitelisted(command, r"systemctl\s+(stop|restart)", env["dev_systemd"], strip_service=True):
        refuse("BLOCKED: systemctl stop/restart/disable/enable/reload/kill/try-restart/reload-or-restart is refused "
                   "for production services", f"Command: {command}",
                   f"Hint: only {env['dev_systemd']} is allowed{f' (and {prefix}-* takes the daemon-restart grant)' if prefix else ''}.",
                   released_line())
    if grep(r"(rm|mv)\s", view) and grep(r"(workflow-[^/]*\.json|\.claude/todos/)", command):
        refuse("BLOCKED: Deleting/moving workflow state files is refused", f"Command: {command}",
                   "These files are required by the workflow enforcement system.", released_line())


# ── Removal policy (BS-32, BS-33) ────────────────────────────────────────────

def removal_policy(payload_text, command):
    """Every execution boundary must be proven inert or a safe removal by lib/bash_execution_boundary.py.

    The analyzer runs in its own process under a time and memory limit. When it gives no usable verdict the
    command passes only if it is provably plain: no removal reference (lib/pol_degraded_removal_reference.ere), no
    assembly channel (expansion, substitution, glob, brace, bang, heredoc, line continuation), and no trailing
    option or operator.
    """
    analyzer = os.path.join(LIB, "bash_execution_boundary.py")
    decision = ""
    limit = duration(os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT", ""), "5s")
    if os.access(analyzer, os.R_OK) and limit is not None:
        try:
            mem_kb = int(os.environ.get("CLAUDE_HOOK_BOUNDARY_MEM_KB", "") or "524288")
        except ValueError:
            mem_kb = None

        def cap():
            if mem_kb is not None:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_kb * 1024, mem_kb * 1024))
                except (ValueError, OSError):
                    pass
        try:
            p = subprocess.run([sys.executable, analyzer], input=payload_text, capture_output=True, text=True,
                               env=dict(os.environ, CMD_INPUT=command, CMD_PAYLOAD="stdin"),
                               timeout=limit or None, preexec_fn=cap)
            if p.returncode == 0:
                v = json.loads(p.stdout)
                verdict = v.get("verdict") if isinstance(v, dict) and v.get("schema") == "bash-execution-boundary.v1" else None
                if verdict in ("PROVEN_INERT", "PROVEN_SAFE_REMOVAL") and v.get("allowed") is True:
                    decision = "ALLOW"
                elif verdict in ("PROVEN_INERT", "PROVEN_SAFE_REMOVAL", "FORBIDDEN_REMOVAL", "UNRESOLVED") \
                        and v.get("allowed") is False:
                    decision = "DENY " + verdict + " " + str(v.get("reason", ""))[:200]
        except Exception:  # noqa: BLE001 - timeout, memory ceiling, crash, bad JSON: degraded mode
            decision = ""
    if decision == "ALLOW":
        return
    if decision.startswith("DENY "):
        refuse(f"BLOCKED: removal-policy — {decision[5:]}", f"Command: {command}",
                   "REASON: every execution boundary must be provably inert or a provably non-filesystem removal (e.g. "
                   "git rm --cached, docker container rm) or a recoverable git rm (no -f, outside the harness home, no "
                   "submodule); this command has a boundary that is none of these.", released_line())
    ere_file = os.path.join(LIB, "pol_degraded_removal_reference.ere")
    try:
        with open(ere_file, encoding="utf-8", errors="replace") as fh:
            rmref = next((ln.rstrip("\n") for ln in fh if not re.match(r"^\s*#", ln) and not re.match(r"^\s*$", ln)), "")
    except OSError:
        rmref = ""
    if not rmref:
        refuse(f"BLOCKED: removal-policy FAIL-CLOSED — the degraded removal-reference predicate at {ere_file} is "
                   f"missing or empty. Denied conservatively.", f"Command: {command}")
    if grep(rmref, command) or grep(r"[\]$`\[?*{}!]|<<", command) or grep(r"\\$", command) \
            or grep(r"(^|[ \t])[-+][A-Za-z0-9=_-]*[ \t]*$", command) or grep(r"[<>|&;][ \t]*$", command):
        refuse("BLOCKED: removal-policy FAIL-CLOSED — the execution-boundary analyzer is unavailable or returned no "
                   "usable verdict, and this command is not provably plain. Denied conservatively.",
                   f"Command: {command}", f"REASON: repair the analyzer deployment at {analyzer}; never widen this "
                   f"fallback to allow.")


def kill_pid_rule(command, view):
    """BS-35: kill <pid>."""
    if grep(r"(^|[;&|]\s*)kill\s+[0-9]", view):
        refuse("BLOCKED: kill with PIDs is refused — verify the target is safe before killing", f"Command: {command}",
                   "REASON: Killing a PID can cascade to unrelated processes. Use a scoped restart instead.",
                   released_line())


# ── Working-tree git rules (BS-36..BS-39, BS-43) ─────────────────────────────

def _wide_path_after_dashdash(args):
    try:
        dd = args.index("--")
    except ValueError:
        return False
    path = args[dd + 1] if dd + 1 < len(args) else ""
    return path in (".", "*") or path.endswith("/")


def worktree_git_rules(command, view):
    """git stash (push forms and bare), wide-path checkout and restore from a ref."""
    bad = {"push", "save", "create", "store", "-u", "--include-untracked", "-a", "--all"}
    first = (view.outer("stash") or [None])[0]
    pq_destructive = first is not None and (not first["args"] or first["args"][0] in bad or (
        first["args"][0].startswith("-") and not first["args"][0].startswith("--") and any(c in first["args"][0][1:] for c in "ua")))
    if grep(r"git\s+stash\s+(push|save|create|store|-u|--include-untracked|-a|--all)\b", command) \
            or grep(r"git\s+stash\s+-[ua]+\b", command) or pq_destructive:
        refuse("BLOCKED: 'git stash push/save/create/store/-u/--all' requires explicit user approval",
                   f"Command: {command}",
                   "REASON: a stash used as a throwaway buffer before a wide checkout can silently lose work; "
                   "-u/--include-untracked/-a/--all also take untracked and ignored files.",
                   "Tell the user what you want to do and ask them to run it, or use commit/branch.", released_line())
    if grep(r"git\s+stash\s*($|[;&|])", command) or any(not i["args"] for i in view.outer("stash")):
        refuse("BLOCKED: bare 'git stash' (implicit push) requires explicit user approval", f"Command: {command}",
                   "Safe stash subcommands are exempt: list, show, pop, apply, drop, clear, branch.", released_line())
    if grep(r"git\s+checkout\s+\S+\s+--\s+(\.|\*|[^ ]+/)\s*($|[;&|])", command) \
            or any(_wide_path_after_dashdash(i["args"]) for i in view.outer("checkout")):
        refuse("BLOCKED: 'git checkout <ref> -- .' / '-- *' / '-- dir/' requires explicit user approval",
                   f"Command: {command}",
                   "REASON: a wide-path checkout from a commit overwrites a whole subtree with old content.",
                   "Allowed: 'git checkout <ref> -- path/to/specific-file.ts' (single file).",
                   "If you need a subtree restore, tell the user what you need and why.", released_line())
    pq_restore = any(any(a in ("--source", "-s") or a.startswith(("--source=", "-s=")) for a in i["args"])
                     and _wide_path_after_dashdash(i["args"]) for i in view.outer("restore"))
    if (grep(r"git\s+restore\b", command) and grep(r"(--source\b|-s\b)", command)
            and grep(r"--\s+(\.|\*|[^ /]+/)\s*($|[;&|])", command)) or pq_restore:
        refuse("BLOCKED: 'git restore --source=<ref> -- .' / '-- *' / '-- dir/' requires explicit user approval",
                   f"Command: {command}",
                   "REASON: it is 'git checkout <ref> -- .' under another name: it overwrites the working tree with old "
                   "content.", "Allowed: 'git restore -- path/to/specific-file.ts' (no --source, or a specific file).",
                   "If you need a subtree restore, tell the user what you need and why.", released_line())


# The `git … clean` occurrence grammar, shared by the per-invocation verdict and the fail-closed scan. A global
# option is (1) a value-taking option with a plain separate value, (2) any option word, or (3) a value-shaped word
# (one holding a character no subcommand name has). The branches are disjoint so each token has one parse and the
# cost stays linear; hooks/tests/test_bash_safety_git_clean.py pins both the reach and the cost.
GC_SEP = r"[\s;&|()`]"
GC_NOSEP = r"""[^\s;&|()`'"]*"""
GC_PATH = f"({GC_NOSEP}/)?"
GC_QVAL = r"[^\s;&|()`]*"
GC_VALOPT_NAMES = "git-dir|work-tree|namespace|exec-path|super-prefix|config-env|attr-source|shallow-file"
GC_VMARK = "/.=:~@%A-Z0-9"
GC_PLAINTOK = rf"[^-\s;&|()`{GC_VMARK}][^\s;&|()`{GC_VMARK}]*"
GC_VALTOK = rf"({GC_PLAINTOK})?[{GC_VMARK}][^\s;&|()`]*"
GC_GOPT = rf"(\s+(-[Cc]\s+{GC_PLAINTOK}|--({GC_VALOPT_NAMES})\s+{GC_PLAINTOK}|-{GC_QVAL}|{GC_VALTOK}))*"
GC_GIT = rf"""(({GC_PATH}git)|"{GC_PATH}git"|'{GC_PATH}git')"""
GIT_CLEAN_OCCURRENCE_RE = rf"""(^|{GC_SEP}){GC_GIT}{GC_GOPT}\s+["']?clean\b"""
# A shell in command position: a word ending in `sh` with an optional version, quoted or not.
GC_SHW = r"""[^\s;&|()`'"*?]*sh[0-9]*"""
GC_SHELL_RE = rf"""(^|{GC_SEP})(({GC_SHW})|"{GC_SHW}"|'{GC_SHW}')(\s|$)"""
# A git subcommand that runs its argument as a command.
GC_ANYTOK = r"(\s+[^\s;&|()`]+)*"
GC_EXECCTX_RE = (rf"(^|{GC_SEP}){GC_GIT}{GC_GOPT}\s+(rebase{GC_ANYTOK}\s+(-x|--exec)|submodule{GC_ANYTOK}\s+foreach"
                 rf"|filter-branch{GC_ANYTOK}\s+(--[a-z]+-filter|--setup)|bisect{GC_ANYTOK}\s+run"
                 rf"|difftool{GC_ANYTOK}\s+(--extcmd|-x)|grep{GC_ANYTOK}\s+--open-files-in-pager)\b")


def git_clean_verdict(command, view):
    """ALLOW only for a provable dry run; BLOCK:nested / BLOCK:trust / BLOCK:exclude / BLOCK:dryrun otherwise.

    Trust first: every argument is written as a plain literal and read statically (T1), and no xargs injects
    arguments (T3). Then a separate-value exclude eats the next token, and the effective
    dry-run state is read up to the first `--`, last one wins, default off.
    """
    from lib.shell_parse import resolve
    literal = re.compile(r'^[A-Za-z0-9_./=+:@,-]*$')
    pos_dry = re.compile(r'^--d(r(y(-(r(u(n)?)?)?)?)?)?$')
    neg_dry = re.compile(r'^--no-d(r(y(-(r(u(n)?)?)?)?)?)?$')
    exclude = re.compile(r'^--e(x(c(l(u(d(e)?)?)?)?)?)?$')
    cluster = re.compile(r'^-[A-Za-z]+$')
    coarse, shell_cmd, exec_ctx = (re.compile(p) for p in (GIT_CLEAN_OCCURRENCE_RE, GC_SHELL_RE, GC_EXECCTX_RE))
    raw = [i for i in view.invs if i["subcommand"] == "clean"]
    # More `git … clean` occurrences than resolved invocations means one sits where the walk cannot see it.
    if shell_cmd.search(command) or exec_ctx.search(command):
        found = max(len(coarse.findall(command.replace('"', q).replace("'", q))) for q in (' ', ''))
    else:
        found = len(coarse.findall(command))
    if found > len([i for i in raw if not i["nested"]]):
        return 'BLOCK:nested'
    for inv in raw:
        g = inv["git"]
        injected = g.cmd is not None and any(w[0] == "xargs" for w in resolve(g.cmd).wrappers)
        if injected or g.unresolved or None in g.args or not all(literal.match(w.text) for w in g.arg_words):
            return 'BLOCK:trust'
        args = inv["args"]
        if any(a == '-e' or (cluster.match(a) and a.endswith('e')) or (exclude.match(a) and '=' not in a) for a in args):
            return 'BLOCK:exclude'
        state = False
        for a in args:
            if a == '--':
                break
            if a == '-n' or pos_dry.match(a):
                state = True
            elif neg_dry.match(a):
                state = False
            elif cluster.match(a) and 'n' in a[1:]:
                first_e = a[1:].find('e')
                if first_e < 0 or a[1:].index('n') < first_e:
                    state = True
        if not state:
            return 'BLOCK:dryrun'
    return 'ALLOW'


def git_clean_rule(command, stripped, view):
    """BS-43: `git clean` passes only as a provable dry run. A clean the classifier cannot resolve (a wrapper prefix,
    a nested shell payload) is found by the occurrence grammar over the raw text and the executable view, with quotes
    neutralised when a shell or an exec-taking git subcommand holds command position, and fails closed."""
    has_inv = view.ok and view.any_sub("clean")
    verdict = ""
    if has_inv:
        try:
            verdict = git_clean_verdict(command, view)
        except Exception:  # noqa: BLE001
            verdict = ""
    probe = ""
    if "clean" in command + stripped and grep(GC_SHELL_RE + "|" + GC_EXECCTX_RE, command + "\n" + stripped):
        probe = (command.replace('"', ' ') + "\n" + stripped.replace('"', ' ')).replace("'", " ")
        probe = (probe + "\n" + command.replace('"', '') + "\n" + stripped.replace('"', '')).replace("'", "")
    fail_closed = not has_inv and grep(GIT_CLEAN_OCCURRENCE_RE, command + "\n" + stripped + "\n" + probe)
    detail = {
        "BLOCK:trust": ["DETAIL: the argument region is not a provable literal (quoting, backslash, $-expansion, brace, "
                        "~, ^, or an argument-injecting xargs wrapper), so what git receives cannot be proven to match "
                        "what was inspected.", "Re-run the preview unquoted and unexpanded, or ask the user for a grant."],
        "BLOCK:exclude": ["DETAIL: a separate-value exclude (-e, a cluster ending in 'e', or --e..--exclude) consumes the "
                          "NEXT token as its pattern, so a following -n is not a dry-run.",
                          "Use the self-contained form '--exclude=<pattern>' alongside -n."],
        "BLOCK:nested": ["DETAIL: the command carries MORE 'git clean' occurrences than can be resolved into invocations "
                         "— at least one is inside a nested shell payload, so it cannot be proven non-destructive even "
                         "though another clean in the same command is a dry-run.",
                         "Issue the dry-run preview on its own, without the nested shell."],
    }.get(verdict) or (["DETAIL: a 'git clean' subcommand is present but could not be resolved into a provable invocation "
                        "(a wrapper prefix such as 'env -i' / 'command --' / 'time -p', or a nested shell payload such "
                        "as \"sh -c '…'\"); failing closed."] if fail_closed else
                       ["DETAIL: the EFFECTIVE dry-run state is OFF for at least one clean invocation (negation is "
                        "last-wins; tokens after '--' are pathspecs, not flags)."])
    if (has_inv and verdict != "ALLOW") or fail_closed:
        refuse("BLOCKED: destructive 'git clean' is refused in agent flow", f"Command: {command}",
               "REASON: git clean removes UNTRACKED files — no rm, no reflog, no reachable git object, so the deletion "
               "is unrecoverable and leaves no trace.", *detail,
               "Allowed: a provable dry-run preview — 'git clean -n', 'git clean -nd', 'git clean -n --exclude=build'.",
               "Escape: the user can authorize this specific command via /do consent or an /allow grant.")


# ── session_dirs.txt (before /do and /allow) ─────────────────────────────────

SD_NAME = "session_dirs.txt"
# Pieces of the name a glob or expansion carries when it is written to land on the file (`sess*`, `*_dirs.t?t`).
SD_FRAGMENTS = ("sess", "_dir", "dirs", "on_d", "n_di")
_SD_DECODE = (
    (re.compile(r"\\[xX]([0-9a-fA-F]{1,2})"), 16),
    (re.compile(r"\\u([0-9a-fA-F]{4})"), 16),
    (re.compile(r"\\U([0-9a-fA-F]{8})"), 16),
    (re.compile(r"\\0?([0-7]{1,3})"), 8),
)
_SD_DROP = re.compile(r"""['"\\$+`\s]""")
_SD_HEAD_DIRS = ("/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin")
# What can change which program a search or commit call runs, or what it reads: a shell function of that name
# (read with quotes, blanks and escapes gone), a command that defines one or an alias or rehashes a path, and a
# variable that moves the program, its options or its config.
_SD_FUNCTION = re.compile(r"(^|[^a-z0-9_])(e|f)?(grep|rg|git)\(\)|function(e|f)?(grep|rg|git)([^a-z0-9_-]|$)")
_SD_DEFINERS = frozenset({"alias", "hash", "enable", "eval", "source", ".", "trap"})
_SD_VARIABLE = re.compile(r"(PATH|GREP_OPTIONS|RIPGREP_CONFIG_PATH|GIT_[A-Z0-9_]*|BASH_ENV|ENV|LD_PRELOAD|"
                          r"LD_LIBRARY_PATH|DYLD_[A-Z_]*)(\[[^\]]*\])?\+?=")
_SD_INTERPRETER = re.compile(r"(python[0-9.]*|pypy[0-9.]*|node(js)?|deno|bun|perl[0-9.]*|ruby|php[0-9.]*|lua(jit)?|"
                             r"osascript|rscript|julia|tclsh|wish|expect|[gmn]?awk)")

# Search programs: (short value options, short flags, long value options, long flags, long options with an optional
# `=value`, options that refuse the mention because they run a program or drop the pattern operand).
_SD_GREP = ("efmABCdD", "abcEFGhHiIlLnoPqrRsTuUvVwxyzZ",
            {"--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context", "--directories",
             "--devices", "--include", "--exclude", "--exclude-from", "--exclude-dir", "--label", "--binary-files",
             "--group-separator"},
            {"--extended-regexp", "--fixed-strings", "--basic-regexp", "--perl-regexp", "--ignore-case",
             "--no-ignore-case", "--word-regexp", "--line-regexp", "--null-data", "--no-messages", "--invert-match",
             "--byte-offset", "--line-number", "--no-line-number", "--line-buffered", "--with-filename",
             "--no-filename", "--only-matching", "--quiet", "--silent", "--text", "--recursive",
             "--dereference-recursive", "--files-without-match", "--files-with-matches", "--count", "--initial-tab",
             "--null", "--no-group-separator", "--binary"},
            {"--color", "--colour"}, set())
_SD_RG = ("efgtTmABCdMjEr", "aAbcFHhiIlLnNopqsSuUvVwx0",
          {"--regexp", "--file", "--glob", "--iglob", "--type", "--type-not", "--type-add", "--type-clear",
           "--max-count", "--after-context", "--before-context", "--context", "--max-depth", "--maxdepth",
           "--max-filesize", "--max-columns", "--threads", "--encoding", "--engine", "--sort", "--sortr", "--colors",
           "--context-separator", "--field-match-separator", "--field-context-separator", "--path-separator",
           "--replace", "--dfa-size-limit", "--regex-size-limit", "--ignore-file", "--pre-glob", "--hyperlink-format"},
          {"--hidden", "--no-hidden", "--no-ignore", "--ignore", "--no-ignore-vcs", "--no-ignore-parent",
           "--no-ignore-dot", "--no-ignore-global", "--no-ignore-exclude", "--no-ignore-files", "--no-require-git",
           "--files-with-matches", "--files-without-match", "--count", "--count-matches", "--line-number",
           "--no-line-number", "--column", "--no-column", "--heading", "--no-heading", "--with-filename",
           "--no-filename", "--ignore-case", "--smart-case", "--case-sensitive", "--fixed-strings",
           "--no-fixed-strings", "--word-regexp", "--line-regexp", "--invert-match", "--multiline",
           "--multiline-dotall", "--only-matching", "--json", "--vimgrep", "--follow", "--no-follow", "--text",
           "--binary", "--no-binary", "--pcre2", "--no-pcre2", "--crlf", "--no-crlf", "--null", "--null-data", "--trim",
           "--stats", "--quiet", "--passthru", "--passthrough", "--unrestricted", "--no-messages", "--no-config",
           "--byte-offset", "--debug", "--trace", "--pretty", "--one-file-system", "--no-unicode", "--auto-hybrid-regex",
           "--no-pcre2-unicode", "--mmap", "--no-mmap", "--block-buffered", "--line-buffered", "--include-zero",
           "--max-columns-preview", "--glob-case-insensitive", "--ignore-file-case-insensitive", "--sort-files"},
          {"--color", "--colour"},
          {"--pre", "--hostname-bin", "--files", "--type-list", "--search-zip", "-z", "--generate"})
_SD_GIT_GREP = ("efABCm", "aiIwvhHEGFPnlLcopWzqr",
                {"--max-depth", "--threads", "--context", "--after-context", "--before-context", "--max-count"},
                {"--cached", "--untracked", "--no-index", "--index", "--no-exclude-standard", "--exclude-standard",
                 "--recurse-submodules", "--text", "--no-textconv", "--ignore-case", "--word-regexp",
                 "--invert-match", "--full-name", "--extended-regexp", "--basic-regexp", "--perl-regexp",
                 "--fixed-strings", "--line-number", "--column", "--files-with-matches", "--name-only",
                 "--files-without-match", "--null", "--only-matching", "--count", "--show-function",
                 "--function-context", "--break", "--heading", "--all-match", "--quiet", "--and", "--or", "--not",
                 "--no-color"},
                {"--color"}, {"--textconv", "-O", "--open-files-in-pager"})
_SD_GIT_GLOBAL_FLAGS = {"--no-pager", "-p", "--paginate", "-P", "--no-optional-locks", "--no-replace-objects",
                        "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"}
# git log options. A value option takes the next word (or its `=value`); a flag takes nothing; an attached option
# takes a value only after `=` (git reads an optional or `=`-only value, as `--unified[=<n>]` or `--orderfile=<f>`, never
# from the next word, so such an option is a flag or attached-only, never a value option). An option on none of these lists (a new one included) leaves no allowed mention, since
# one that takes the next word would shift `-S` into value position and the name after it into a pathspec.
_SD_LOG_VALUES = {"-n", "--max-count", "--skip", "--since", "--after", "--until", "--before", "--author",
                  "--committer", "--grep-reflog", "--find-object", "-L", "-O",
                  "-I", "--ignore-matching-lines", "--exclude", "--word-diff-regex", "--anchored", "--rotate-to",
                  "--skip-to", "--line-prefix", "--src-prefix", "--dst-prefix", "--max-age", "--min-age",
                  "--since-as-filter", "--decorate-refs", "--decorate-refs-exclude", "--diff-algorithm",
                  "--inter-hunk-context", "--output-indicator-new", "--output-indicator-old",
                  "--output-indicator-context", "--ws-error-highlight", "--stat-width", "--stat-name-width",
                  "--stat-graph-width", "--stat-count", "--date", "--encoding", "--diff-merges", "--default",
                  "--exclude-hidden"}
_SD_LOG_FLAGS = {"-p", "-u", "--patch", "-s", "--no-patch", "-i", "--regexp-ignore-case", "-E", "--extended-regexp",
                 "-F", "--fixed-strings", "-P", "--perl-regexp", "--basic-regexp", "--all-match", "--invert-grep",
                 "--oneline", "--all", "--branches", "--tags", "--remotes", "--reverse", "--graph", "--no-graph",
                 "--decorate", "--no-decorate", "--abbrev-commit", "--no-abbrev-commit", "--no-abbrev", "--merges",
                 "--no-merges", "--first-parent", "--follow", "--no-follow", "--pickaxe-all", "--pickaxe-regex",
                 "--date-order", "--author-date-order", "--topo-order", "--no-color", "--source", "--full-history",
                 "--simplify-merges", "--simplify-by-decoration", "--ancestry-path", "--dense", "--sparse", "--stat",
                 "--shortstat", "--numstat", "--summary", "--name-only", "--name-status", "--raw", "--compact-summary",
                 "--relative-date", "--left-right", "--boundary", "--cherry-pick", "--cherry-mark", "--cherry",
                 "--left-only", "--right-only", "--full-diff", "--no-renames", "-M", "-C", "-B", "--text", "-a",
                 "-w", "--ignore-all-space", "-b", "--ignore-space-change", "--ignore-blank-lines",
                 "--ignore-space-at-eol", "--ignore-cr-at-eol", "--minimal", "--patience", "--histogram", "-m", "-c",
                 "--cc", "-r", "-t", "-R", "-W", "--function-context", "--log-size", "--no-notes", "--show-signature",
                 "--no-ext-diff", "--no-textconv", "-g", "--walk-reflogs", "--use-mailmap", "--mailmap",
                 "--no-mailmap", "--no-use-mailmap", "--full-index", "--binary", "--check", "--quiet", "--exit-code",
                 "--no-walk", "--do-walk", "--parents", "--children", "--show-pulls", "--remove-empty", "--no-prefix",
                 "--default-prefix", "--clear-decorations", "--count", "--no-diff-merges", "--combined-all-paths",
                 "--no-min-parents", "--no-max-parents", "--show-linear-break", "--expand-tabs", "--no-expand-tabs",
                 "--word-diff", "--color-words", "--color", "--color-moved", "--no-color-moved", "--submodule",
                 "--relative", "--no-relative", "--abbrev", "--notes", "--show-notes", "--standard-notes",
                 "--no-standard-notes", "--dirstat", "--cumulative", "--indent-heuristic", "--no-indent-heuristic",
                 "--find-renames", "--find-copies", "--find-copies-harder", "--break-rewrites", "--unified"}
_SD_LOG_ATTACHED = {"--format", "--pretty", "--abbrev", "--decorate", "--color", "--color-moved", "--word-diff",
                    "--color-words", "--stat", "--dirstat", "--diff-filter", "--relative", "--notes", "--show-notes",
                    "--submodule", "--branches", "--tags", "--remotes", "--glob", "--expand-tabs",
                    "--show-linear-break", "--no-walk", "--color-moved-ws", "--ignore-submodules", "--simplify-merges",
                    "--ancestry-path", "--find-renames", "--find-copies", "--break-rewrites", "--unified",
                    "--min-parents", "--max-parents", "--orderfile"}
_SD_LOG_SHORT_ATTACHED = "nUMCBlIO"  # a short option whose value may follow it in the same word, as `-n5` or `-U3`
_SD_COMMIT_SHORT_VALUES = "mFCct"
_SD_COMMIT_SHORT_OPTIONAL = "Su"
_SD_COMMIT_SHORT_FLAGS = "aqvsneiopz"
_SD_COMMIT_LONG_VALUES = {"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author",
                          "--date", "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file"}
_SD_COMMIT_LONG_FLAGS = {"--all", "--patch", "--quiet", "--verbose", "--signoff", "--no-signoff", "--no-verify",
                         "--verify", "--amend", "--no-edit", "--edit", "--allow-empty", "--allow-empty-message",
                         "--dry-run", "--short", "--branch", "--porcelain", "--long", "--null", "--include", "--only",
                         "--reset-author", "--status", "--no-status", "--no-post-rewrite", "--no-gpg-sign",
                         "--interactive", "--gpg-sign", "--untracked-files"}


def _sd_writes_output(arg):
    """True when a git option sends the output to a file: --output in any abbreviation git accepts, or -o."""
    name = arg.partition("=")[0]
    return name == "-o" or (name.startswith("-o") and not name.startswith("--")) or \
        (len(name) >= 4 and "--output".startswith(name)) or name == "--output"


def sd_normalize(text):
    """text as the name check reads it: escapes decoded, lower case, quotes, `$`, `+`, backslashes and blanks gone."""
    for rx, base in _SD_DECODE:
        text = rx.sub(lambda m: chr(int(m.group(1), base) % 0x110000), text)
    return _SD_DROP.sub("", text.lower())


def _sd_scan(args, spec, permute=True, operands=None):
    """The arg indexes a grep-like program reads as its pattern; None when an option is unknown or refuses the name.
    operands, when given, receives the indexes of the other positional words (paths, revisions, pathspecs)."""
    short_val, short_flag, long_val, long_flag, long_opt, refused = spec
    patterns, positional, explicit, k, dashdash = set(), [], False, 0, False
    while k < len(args):
        a = args[k]
        if dashdash or a == "-" or not a.startswith("-") or (positional and not permute):
            positional.append(k)
            k += 1
            continue
        if a == "--":
            dashdash = True
            k += 1
            continue
        if a.startswith("--"):
            name, eq, _val = a.partition("=")
            if name in refused:
                return None
            if name in long_val:
                if name in ("--regexp", "--file"):
                    explicit = True
                if name == "--regexp":
                    patterns.add(k if eq else k + 1)
                k += 1 if eq else 2
                continue
            if name in long_opt or (name in long_flag and not eq):
                k += 1
                continue
            return None
        if a[:2] in refused:
            return None
        j = 1
        while j < len(a):
            c = a[j]
            if c in short_val:
                if c in "ef":
                    explicit = True
                if c == "e":
                    patterns.add(k if j + 1 < len(a) else k + 1)
                if j + 1 >= len(a):
                    k += 1
                break
            if c not in short_flag and not c.isdigit():
                return None
            j += 1
        k += 1
    if not explicit and positional:
        patterns.add(positional[0])
    if operands is not None:
        operands.extend(i for i in positional if i not in patterns)
    return patterns


def _sd_git(args):
    """(allowed arg indexes, message comes from stdin) for a git call that names the file only as a search pattern
    or in a commit message; None when any part of it is not read."""
    k = 0
    while k < len(args) and args[k].startswith("-"):
        if args[k] == "-C" and k + 1 < len(args):
            k += 2
            continue
        if args[k] not in _SD_GIT_GLOBAL_FLAGS:
            return None
        k += 1
    if k >= len(args):
        return None
    sub, rest, base = args[k], args[k + 1:], k + 1
    if sub == "grep":
        found = _sd_scan(rest, _SD_GIT_GREP, permute=False)
        return None if found is None else ({base + i for i in found}, False)
    if sub == "log":
        allowed, j = set(), 0
        while j < len(rest):
            a = rest[j]
            if a == "--":
                break
            if a == "--ext-diff" or _sd_writes_output(a):
                return None
            if a in ("-S", "-G", "--grep"):
                allowed.add(base + j + 1)
                j += 2
                continue
            if (a[:2] in ("-S", "-G") and len(a) > 2) or a.startswith("--grep="):
                allowed.add(base + j)
            elif a in _SD_LOG_VALUES:
                j += 2
                continue
            elif a.startswith("-") and a != "-":
                name, eq, _val = a.partition("=")
                known = (a in _SD_LOG_FLAGS or re.fullmatch(r"-[0-9]+", a)
                         or (eq and name.startswith("--") and (name in _SD_LOG_VALUES or name in _SD_LOG_ATTACHED))
                         or (not a.startswith("--") and len(a) > 2 and a[1] in _SD_LOG_SHORT_ATTACHED))
                if not known:
                    return None
            j += 1
        return allowed, False
    if sub == "commit":
        allowed, stdin, j = set(), False, 0
        while j < len(rest):
            a = rest[j]
            if a == "--" or not a.startswith("-") or a == "-":
                return allowed, stdin  # a pathspec follows: its words are not messages
            if a.startswith("--"):
                name, eq, val = a.partition("=")
                if name in _SD_COMMIT_LONG_VALUES:
                    value_at = j if eq else j + 1
                    value = val if eq else (rest[j + 1] if j + 1 < len(rest) else None)
                    if name == "--message":
                        allowed.add(base + value_at)
                    if name == "--file" and value in ("-", "/dev/stdin"):
                        stdin = True
                    j += 1 if eq else 2
                    continue
                if name in _SD_COMMIT_LONG_FLAGS:
                    j += 1
                    continue
                return None
            c_at = 1
            while c_at < len(a):
                c = a[c_at]
                if c in _SD_COMMIT_SHORT_VALUES:
                    attached = c_at + 1 < len(a)
                    value = a[c_at + 1:] if attached else (rest[j + 1] if j + 1 < len(rest) else None)
                    if c == "m":
                        allowed.add(base + (j if attached else j + 1))
                    if c == "F" and value in ("-", "/dev/stdin"):
                        stdin = True
                    if not attached:
                        j += 1
                    break
                if c in _SD_COMMIT_SHORT_OPTIONAL:
                    break
                if c not in _SD_COMMIT_SHORT_FLAGS:
                    return None
                c_at += 1
            j += 1
        return allowed, stdin
    return None


def _sd_message_doc(word):
    """The heredoc of a word that is one `"$(cat <<'EOF' ... EOF)"` and nothing else; None otherwise."""
    from lib.shell_parse import SimpleCommand
    if len(word.parts) != 1 or word.parts[0].kind != "cmdsub" or word.parts[0].quote != "double":
        return None
    body = word.parts[0].body
    if body is None or body.error is not None or len(body.items) != 1 or len(body.items[0][0].stages) != 1:
        return None
    inner = body.items[0][0].stages[0]
    if not isinstance(inner, SimpleCommand) or inner.assignments or [w.value() for w in inner.words] != ["cat"]:
        return None
    if len(inner.redirects) != 1 or inner.redirects[0].op not in ("<<", "<<-"):
        return None
    hd = inner.redirects[0].hd
    return hd if hd is not None and (hd.quoted or not hd.expansions) else None


def _sd_allowed(site):
    """The Srcs of one walked command that name the file only as a search pattern or a commit message: the words,
    and the heredoc or here-string that is the message."""
    from lib.shell_parse import resolve
    cmd = site.cmd
    if site.templated or not cmd.words or cmd.assignments:
        return []
    try:
        res = resolve(cmd)
    except Exception:  # noqa: BLE001
        return []
    if res.unresolved or res.head is None or res.payload is not None or res.assignments:
        return []
    hv = res.head.value()
    if hv is None or ("/" in hv and hv.rsplit("/", 1)[0] not in _SD_HEAD_DIRS):
        return []
    docs = {}
    args = []
    for k, w in enumerate(res.args):
        v = w.value()
        if v is None or any(p.kind != "lit" for p in w.parts):
            hd = _sd_message_doc(w) if res.name == "git" else None
            if hd is None:
                return []
            docs[k] = hd
            v = "message"
        args.append(v)
    stdin = False
    if res.name in ("grep", "egrep", "fgrep"):
        found = _sd_scan(args, _SD_GREP)
    elif res.name == "rg":
        found = _sd_scan(args, _SD_RG)
    elif res.name == "git":
        git = _sd_git(args)
        found, stdin = git if git is not None else (None, False)
    else:
        found = None
    if found is None or not set(docs) <= found:
        return []
    out = [res.args[i].raw for i in found if i < len(res.args)]  # a message `$(cat <<'EOF' ..)` is inert text
    if stdin:
        for r in cmd.redirects:
            if r.fd == 0 and r.op in ("<<", "<<-") and r.hd is not None and (r.hd.quoted or not r.hd.expansions):
                out.append(r.hd.body_src)
            elif r.fd == 0 and r.op == "<<<" and r.target is not None and r.target.value() is not None \
                    and all(p.kind == "lit" for p in r.target.parts):
                out.append(r.target.raw)
    return out


# Strong pieces of the name a command substitution's text carries when it is written to print it.
_SD_PIECES = ("session_dir", "dirs.txt", "ion_dirs")
_SD_PARAM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SD_CANDIDATES = ("session_dirs.txt", "./session_dirs.txt", "a/session_dirs.txt", "/a/b/session_dirs.txt")
# What an allowed mention's output can be piped into and still only be shown: filters that print what they read,
# each with the only options it may carry (short flags, short options with a value, long flags, long options with
# a value, most operands). Long options are taken only in full (an abbreviation is not read); nothing that reads
# file names from its input (--files0-from), writes a file (sort -o/--output, -T, --compress-program, uniq's second
# operand, less's log file) or reads a file of its own choosing (--random-source) is a display.
_SD_DISPLAY = {
    "head": ("qvz", "nc", {"--quiet", "--silent", "--verbose", "--zero-terminated"}, {"--lines", "--bytes"}, None),
    "tail": ("qvzfFr", "ncs", {"--quiet", "--silent", "--verbose", "--zero-terminated", "--follow", "--retry"},
             {"--lines", "--bytes", "--sleep-interval", "--pid", "--max-unchanged-stats"}, None),
    "wc": ("clmwL", "", {"--bytes", "--chars", "--lines", "--words", "--max-line-length"}, {"--total"}, None),
    "cut": ("snz", "bcfd", {"--complement", "--only-delimited", "--zero-terminated"},
            {"--bytes", "--characters", "--fields", "--delimiter", "--output-delimiter"}, None),
    "nl": ("p", "bdfhilnsvw", {"--no-renumber"},
           {"--body-numbering", "--section-delimiter", "--footer-numbering", "--header-numbering",
            "--line-increment", "--join-blank-lines", "--number-format", "--number-width", "--number-separator",
            "--starting-line-number"}, None),
    "column": ("tnexJL", "sc", {"--table", "--fillrows", "--json", "--keep-empty-lines", "--table-noextreme"},
               {"--separator", "--columns", "--output-width", "--table-columns", "--table-name"}, None),
    "sort": ("bdfgiMhnRrVcCmsuz", "ktS",
             {"--ignore-leading-blanks", "--dictionary-order", "--ignore-case", "--general-numeric-sort",
              "--ignore-nonprinting", "--month-sort", "--human-numeric-sort", "--numeric-sort", "--random-sort",
              "--reverse", "--version-sort", "--check", "--merge", "--stable", "--unique", "--zero-terminated",
              "--debug"},
             {"--key", "--field-separator", "--buffer-size", "--sort", "--parallel"}, None),
    "uniq": ("cdDiuz", "fsw", {"--count", "--repeated", "--ignore-case", "--unique", "--zero-terminated"},
             {"--skip-fields", "--skip-chars", "--check-chars", "--all-repeated", "--group"}, 1),
    "less": ("RSNXFiIrMmEeKqQ", "", set(), set(), None),
    "more": ("dlfpcsu", "", set(), set(), None),
}
# Commands that only list or print the names a glob expands to; a glob in their words lands on no file's content
# while their output is shown and not consumed.
_SD_LISTERS = frozenset({"ls", "dir", "vdir", "du", "echo", "printf", "stat", "find"})
# What a later word can use to reach an earlier command's last argument (`grep -l session_dirs.txt; cat $_`).
_SD_LAST_ARG = re.compile(r"\$(_(?![A-Za-z0-9_])|\{_(?![A-Za-z0-9_])|\{?BASH_(ARGV|ARGC|COMMAND|EXECUTION_STRING)|\{!)"
                          r"|!\$")
_SD_FIND_NAMES = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename"}
_SD_FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
# Interpreters: (short options whose value is code, short options that take the next word, long options whose
# value is code).
_SD_CODE_OPTS = (
    (re.compile(r"(python|pypy)[0-9.]*"), "c", "mWXQ", set()),
    (re.compile(r"node(js)?|bun"), "ep", "r", {"--eval", "--print"}),
    (re.compile(r"deno"), "", "", {"--eval"}),
    (re.compile(r"perl[0-9.]*"), "eE", "", set()),
    (re.compile(r"ruby"), "e", "IrCx", set()),
    (re.compile(r"php[0-9.]*"), "rRBE", "cdfzt", set()),
    (re.compile(r"lua(jit)?|osascript|rscript|julia"), "e", "l", {"--eval", "--expr"}),
    (re.compile(r"expect"), "c", "f", set()),
)


def _sd_strong_piece(text):
    low = sd_normalize(text)
    return any(p in low for p in _SD_PIECES) or ("session" in low and "dirs" in low)


def _sd_variants(word, env):
    """The word's parts, with each variable the command assigns a literal value read as that value."""
    out = [[]]
    for p in word.parts:
        vals = env.get(p.text) if p.kind == "param" and _SD_PARAM_NAME.fullmatch(p.text) else None
        if vals:
            out = [v + [("lit", val)] for v in out for val in sorted(vals)][:32]
        else:
            out = [v + [(p.kind, p.text)] for v in out]
    return out


def _sd_glob_hit(word, env=None):
    """True when a word with a glob or an expansion can resolve to the file: the last component of one of its paths
    (split at `=` and `:`), not a bare expansion, matches the name, and its written text carries a piece of it. A variable the command
    assigns a literal value reads as that value, and a command substitution whose text carries a strong piece of
    the name counts as a hit."""
    import fnmatch
    if all(p.kind == "lit" for p in word.parts):
        return False
    for parts in _sd_variants(word, env or {}):
        comps, pat, frag = [], [], []
        for kind, text in parts:
            if kind == "lit":
                for ch in text:
                    if ch in "/=:":
                        if ch != "/":  # a directory component is not the file; only a path's last one is tested
                            comps.append(("".join(pat), "".join(frag)))
                        pat, frag = [], []
                    else:
                        pat.append("[%s]" % ch if ch in "*?[]" else ch)
                        frag.append(ch)
            elif kind == "glob":
                pat.append(text)
                frag.append(text)
            elif kind in ("brace", "cmdsub", "backtick", "procsub_in", "procsub_out"):
                if kind in ("cmdsub", "backtick") and _sd_strong_piece(text):
                    return True
                pat.append("*")
                frag.append(text)
            else:
                pat.append("*")
        comps.append(("".join(pat), "".join(frag)))
        for pattern, text in comps:
            low = sd_normalize(text)
            if pattern.strip("*"):  # not a bare expansion
                if fnmatch.fnmatchcase(SD_NAME, pattern.lower()) and any(f in low for f in SD_FRAGMENTS):
                    return True
    return False


def _sd_env(sites):
    """name -> the literal values the command assigns it anywhere (plain assignments and export/declare/local)."""
    from lib.shell_parse import Assignment, resolve
    env = {}
    for site in sites:
        found = list(site.cmd.assignments)
        try:
            res = resolve(site.cmd)
            if res.name in ("export", "declare", "typeset", "local", "readonly"):
                found += [Assignment(w) for w in res.args if "=" in w.text]
        except Exception:  # noqa: BLE001
            pass
        for a in found:
            v = a.static_value()
            if a.name and v is not None:
                env.setdefault(a.name, set()).add(v)
    return env


def _sd_pattern_hits(value, regex=False):
    """True when a glob (or find regex) a program applies to file names matches the file and carries a piece of its
    name, whatever quoting the shell saw."""
    import fnmatch
    low = value.lower()
    if not any(f in sd_normalize(low) for f in SD_FRAGMENTS):
        return False
    if regex:
        try:
            return any(re.fullmatch(low, c) for c in _SD_CANDIDATES)
        except re.error:
            return True
    m = re.match(r":(\(([^)]*)\)|[!^/]*)", low)  # a git pathspec's magic
    if m and m.group(0) != ":":
        magic = m.group(2) if m.group(2) is not None else m.group(1)
        if "exclude" in magic or magic.startswith(("!", "^")):
            return False
        low = low[m.end():]
    if not any(c in low for c in "*?["):
        return False
    return any(fnmatch.fnmatchcase(c, low) for c in _SD_CANDIDATES)


def _sd_glob_operand(res, out_safe):
    """The glob a program applies to file names itself (find -name/-path/-regex, rg -g, grep --include, git
    pathspecs, tar --wildcards/--include, rsync --include/--filter) when it matches the file; None otherwise. A
    find that only lists names to the terminal is left alone."""
    name = res.name
    vals = [w.value() if w.value() is not None else w.text for w in res.args]
    hits = []

    def opt_values(longs, shorts=""):
        found, k = [], 0
        while k < len(vals):
            a = vals[k]
            nm, eq, v = a.partition("=")
            if nm in longs:
                if eq:
                    found.append(v)
                elif k + 1 < len(vals):
                    found.append(vals[k + 1])
                    k += 1
            elif shorts and len(a) >= 2 and a[0] == "-" and a[1] in shorts:
                if len(a) > 2:
                    found.append(a[2:])
                elif k + 1 < len(vals):
                    found.append(vals[k + 1])
                    k += 1
            k += 1
        return found

    if name == "find":
        if res.payload is None and not any(v in _SD_FIND_ACTIONS for v in vals) and out_safe:
            return None
        for k, a in enumerate(vals[:-1]):
            if a in _SD_FIND_NAMES and _sd_pattern_hits(vals[k + 1]):
                return vals[k + 1]
            if a in ("-regex", "-iregex") and _sd_pattern_hits(vals[k + 1], regex=True):
                return vals[k + 1]
        return None
    if name == "rg":
        hits = [h for h in opt_values({"--glob", "--iglob"}, "g") if not h.startswith("!")]
    elif name in ("grep", "egrep", "fgrep"):
        hits = opt_values({"--include"})
    elif name == "rsync":
        hits = opt_values({"--include"})
        for r in opt_values({"--filter"}, "f"):
            m = re.match(r"(\+|include)[ ,_]\s*(.*)", r)
            if m:
                hits.append(m.group(2))
    elif name in ("tar", "bsdtar", "gtar"):
        hits = opt_values({"--include"})
        if "--wildcards" in vals:
            hits += [v for v in vals if not v.startswith("-")]
    elif name == "git":
        if "--" in vals:
            hits += vals[vals.index("--") + 1:]
        k = 0
        while k < len(vals) and vals[k].startswith("-"):
            k += 2 if vals[k] == "-C" else 1
        if k < len(vals) and vals[k] == "grep":
            operands = []
            if _sd_scan(vals[k + 1:], _SD_GIT_GREP, permute=False, operands=operands) is not None:
                hits += [vals[k + 1 + i] for i in operands]
        elif k < len(vals) and vals[k] != "commit":  # a pathspec needs no `--` (`git ls-files -o '*dirs*'`)
            j = k + 1
            while j < len(vals):
                if vals[j] in ("-m", "--message", "-F", "--file", "-S", "-G", "--grep", "--output", "-C"):
                    j += 2
                    continue
                if not vals[j].startswith("-"):
                    hits.append(vals[j])
                j += 1
    for h in hits:
        if _sd_pattern_hits(h):
            return h
    return None


def _sd_interpreter_code(res, cmd):
    """The code an interpreter call runs from its own words or its stdin: a -c/-e/-r style option's value (awk's
    program operand), and a heredoc or here-string. A script path and the script's arguments are not code."""
    name = res.name.lower()
    vals = [w.value() if w.value() is not None else w.text for w in res.args]
    code = []
    if re.fullmatch(r"[gmn]?awk", name):
        k, from_file = 0, False
        while k < len(vals):
            a = vals[k]
            if a == "--":
                k += 1
                break
            if not a.startswith("-") or a == "-":
                break
            nm, eq, v = a.partition("=")
            if a in ("-f", "--file") or a.startswith("-f"):
                from_file = True
            if nm in ("-e", "--source"):
                code.append(v if eq else (vals[k + 1] if k + 1 < len(vals) else ""))
                from_file = True
            if a in ("-f", "-v", "-F", "-e", "--file", "--assign", "--field-separator", "--source", "-i", "-l",
                     "--include", "--load"):
                k += 2
                continue
            k += 1
        if not from_file and k < len(vals):
            code.append(vals[k])
    else:
        spec = next((s for s in _SD_CODE_OPTS if s[0].fullmatch(name)), (None, "", "", set()))
        _rx, code_letters, next_letters, longs = spec
        k = 0
        while k < len(vals):
            a = vals[k]
            if a in ("--", "-"):
                break
            if a.startswith("--"):
                nm, eq, v = a.partition("=")
                if nm in longs:
                    code.append(v if eq else (vals[k + 1] if k + 1 < len(vals) else ""))
                    k += 1 if eq else 2
                    continue
                k += 1
                continue
            if a.startswith("-"):
                j, skip = 1, False
                while j < len(a):
                    c = a[j]
                    if c in code_letters:
                        if a[j + 1:]:
                            code.append(a[j + 1:])
                        elif k + 1 < len(vals):
                            code.append(vals[k + 1])
                            skip = True
                        break
                    if c in next_letters:
                        skip = not a[j + 1:]
                        break
                    j += 1
                k += 2 if skip else 1
                continue
            if name == "deno" and a == "eval" and k + 1 < len(vals):
                code.append(vals[k + 1])
            break  # the script; what follows is its arguments
    for r in cmd.redirects:
        if r.hd is not None:
            code.append(r.hd.body)
        elif r.op == "<<<" and r.target is not None:
            code.append(r.target.value() or r.target.text)
    return code


_SD_LITERAL = re.compile(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`((?:[^`\\]|\\.)*)`""", re.S)
# What splits a string literal where a value is interpolated (`{p}`, `${p}`, `$p`, `#{p}`, `%s`).
_SD_INTERPOLATION = re.compile(r"\{[^{}]*\}|\$\{[^}]*\}|\$[a-z_][a-z0-9_]*|#\{[^}]*\}|%[-0-9.]*[a-z]")
# What joins two literals into one string: `+`, `.`, `..`, `~` and juxtaposition.
_SD_JOIN = re.compile(r"[\s+.~]*")


def _sd_literal_runs(code):
    """The strings interpreter code writes: consecutive string literals joined by a concatenation operator, split
    where a value is interpolated or another expression stands between them."""
    runs, cur, last = [], None, 0
    for m in _SD_LITERAL.finditer(code):
        body = next(g for g in m.groups() if g is not None)
        pieces = _SD_INTERPOLATION.split(body)
        if cur is not None and not _SD_JOIN.fullmatch(code[last:m.start()]):
            runs.append(cur)
            cur = None
        cur = (cur or "") + pieces[0]
        for piece in pieces[1:]:
            runs.append(cur)
            cur = piece
        last = m.end()
    if cur is not None:
        runs.append(cur)
    return runs


def _sd_code_names(code):
    """True when interpreter code names the file, builds exactly its name from pieces (a literal run that is the
    name, a strong tail of it a computed head can complete, or a head and a tail that together cover it), or globs
    for it. A run naming another file that merely ends in `dirs.txt` (`build_dirs.txt`) is no hit."""
    if SD_NAME in sd_normalize(code):
        return True
    low = code
    for rx, base in _SD_DECODE:
        low = rx.sub(lambda m: chr(int(m.group(1), base) % 0x110000), low)
    runs = [r for r in _sd_literal_runs(low.lower()) if r]
    tails = [r for r in runs if SD_NAME.endswith(r)]
    if any(len(t) >= len("dirs.txt") for t in tails):
        return True
    heads = [r.rsplit("/", 1)[-1] for r in runs]
    heads = [h for h in heads if h and SD_NAME.startswith(h)]
    if any(len(h) + len(t) >= len(SD_NAME) for h in heads for t in tails):
        return True
    return any(_sd_pattern_hits(g) for g in re.findall(r"""[^\s'"`(),;\[\]]*[*?][^\s'"`(),;\[\]]*""", code))


def _sd_streams(node, out, err):
    """(stdout safe, stderr safe) after a command's own redirections, given whether its stdout and stderr reach only
    the terminal or /dev/null (through display filters at most) before them. A file, another fd or a computed
    target is unsafe: a later command or a later call can read it back."""
    for r in node.redirects:
        if r.op in ("<", "<<", "<<-", "<<<", "<&"):
            continue
        both = r.op in ("&>", "&>>") or (r.op == ">&" and r.io is None and r.dup is None and not r.close)
        fd = None if both else r.fd
        if fd is None and not both:
            out = err = False  # a {NAME}> form
            continue
        if fd not in (1, 2, None):
            continue
        if r.close:
            here = True
        elif r.op == ">&" and r.dup is not None:
            here = (out if r.dup == 1 else err) if r.dup in (1, 2) else False
        elif not r.writes() or r.target is None:
            continue
        else:
            v = r.target.value()
            here = {"/dev/null": True, "/dev/tty": True, "/dev/stdout": out, "/dev/fd/1": out,
                    "/dev/stderr": err, "/dev/fd/2": err}.get(v, False)
        if fd in (1, None):
            out = here
        if fd in (2, None):
            err = here
    return out, err


def _sd_display(stage):
    """True when a pipeline stage only shows what it reads: a display filter with no wrapper, payload or output
    file of its own."""
    from lib.shell_parse import SimpleCommand, resolve
    if not isinstance(stage, SimpleCommand) or stage.assignments:
        return False
    try:
        res = resolve(stage)
    except Exception:  # noqa: BLE001
        return False
    if res.unresolved or res.payload is not None or res.wrappers or res.assignments or res.name not in _SD_DISPLAY:
        return False
    hv = res.head.value()
    if hv is None or ("/" in hv and hv.rsplit("/", 1)[0] not in _SD_HEAD_DIRS):
        return False
    vals = [w.value() for w in res.args]
    if any(v is None for v in vals) or any(r.target is not None and r.target.value() is None for r in stage.redirects):
        return False  # `head $(cat)` reads the pipe through its own words
    return _sd_display_args(_SD_DISPLAY[res.name], vals, res.name in ("head", "tail"))


def _sd_display_args(spec, vals, numeric):
    """True when every option is on the filter's own list and the operands are within its limit."""
    flags, short_vals, long_flags, long_vals, most = spec
    operands, k, dashdash = 0, 0, False
    while k < len(vals):
        a = vals[k]
        k += 1
        if dashdash or a == "-" or not a.startswith(("-", "+")) or (a.startswith("+") and not numeric):
            operands += 1
            continue
        if a == "--":
            dashdash = True
            continue
        if a.startswith("+"):  # tail +5
            if not a[1:].isdigit():
                return False
            continue
        if a.startswith("--"):
            name, eq, _v = a.partition("=")
            if name in long_vals:
                k += 0 if eq else 1
                continue
            if name in long_flags and not eq:
                continue
            return False
        j = 1
        while j < len(a):
            c = a[j]
            if c in short_vals:
                k += 0 if j + 1 < len(a) else 1
                break
            if not (c in flags or (numeric and c.isdigit())):
                return False
            j += 1
    return k <= len(vals) and (most is None or operands <= most)


def _sd_key(context, cmd):
    return (tuple(context), cmd.span, tuple(w.text for w in cmd.words))


def _sd_output_safety(script, traced=False):
    """{key: (stdout safe, stderr safe)} for each simple command the walk reaches through pipelines, compounds and
    payloads: stdout safe when it only reaches the terminal (or /dev/null) through display filters at most, stderr
    safe likewise, carrying the redirections of every enclosing group, loop, subshell and payload shell. When the
    shell may trace (traced), the trace of a command goes to the stderr it inherits, so its stdout counts as safe only
    with that stderr safe too. A command inside a substitution, a function body, a coproc or code the walk reaches
    another way is absent. An `exec` that moves the shell's own stdout or stderr leaves nothing safe."""
    from lib.shell_parse import Compound, SimpleCommand, resolve
    found, moved = {}, []

    def visit(scr, out_ok, err_ok, ctx):
        for pl, _sep in scr.items:
            stages, pipes = list(pl.stages), list(pl.pipes)
            streams, inherited = [None] * len(stages), [None] * len(stages)
            down = out_ok
            for k in range(len(stages) - 1, -1, -1):
                err_in = down if k < len(pipes) and pipes[k] == "|&" else err_ok
                inherited[k] = err_in
                streams[k] = _sd_streams(stages[k], down, err_in)
                down = streams[k][0] and _sd_display(stages[k])
            for k, st in enumerate(stages):
                o, e = streams[k]
                if isinstance(st, SimpleCommand):
                    show = o and (not traced or (inherited[k] and e))
                    key = _sd_key(ctx, st)
                    prev = found.get(key, (True, True))
                    found[key] = (prev[0] and show, prev[1] and e and inherited[k])
                    if [w.value() for w in st.words] == ["exec"] and any(r.writes() or r.op == ">&" for r in st.redirects):
                        moved.append(st)
                    try:
                        res = resolve(st)
                    except Exception:  # noqa: BLE001
                        continue
                    if res.payload is not None and res.payload_kind:
                        visit(res.payload, o, e, ctx + (res.payload_kind,))
                elif isinstance(st, Compound):
                    inner = st.kind not in ("function", "coproc")
                    for body in st.body:
                        visit(body, o and inner, e and inner, ctx)

    visit(script, True, True, ("top",))
    return {k: (False, False) for k in found} if moved else found


def _sd_redefines(site):
    """True when this command can change which program a later search or commit call runs, or what it reads."""
    from lib.shell_parse import resolve
    cmd = site.cmd
    try:
        res = resolve(cmd)
    except Exception:  # noqa: BLE001
        return True
    names = [res.name] + [w[0] for w in res.wrappers]
    if any(n in _SD_DEFINERS for n in names):
        return True
    texts = [a.word.text for a in cmd.assignments] + [a.word.text for a in res.assignments]
    if res.name in ("export", "declare", "typeset", "readonly", "local", "set", "env"):
        texts += [w.value() or w.text for w in res.args]
    return any(_SD_VARIABLE.match(t.lstrip("'\"")) for t in texts)


# What reads an allowed mention's own text back once the call has run: the shell's command line in /proc, the
# commit message file and anything else under .git, the shell's history, and the process lists.
_SD_READBACK = re.compile(r"(^|[^a-z0-9_.-])proc([^a-z0-9_.-]|$)|cmdline|/self/|thread-self|\$\$|\$\{?(bashpid|ppid)|"
                          r"editmsg|(^|[^a-z0-9_.-])\.git([^a-z0-9_-]|$)|git-dir|git-path|git-common|git_dir|"
                          r"histfile|_history")
_SD_READBACK_GLOB = (".git", "proc", "cmdline", "commit_editmsg", "self", "thread-self")
_SD_READBACK_PROGRAMS = frozenset({"ps", "pgrep", "pkill", "pstree", "top", "htop", "atop", "btop", "procs", "pidof",
                                   "fc", "history", "jobs", "w", "lsof", "fuser"})
# git subcommands that never print a commit's message; any other git call after a commit-message mention must show
# its output (stdout and stderr) only.
_SD_GIT_QUIET = frozenset({"add", "push", "status", "fetch", "init", "rm", "mv", "restore", "diff", "ls-files",
                           "ls-tree", "config", "remote", "rev-parse", "check-ignore", "version", "help", "grep"})
_SD_SHELL = re.compile(r"(ba|da|z|k|mk|y|r|po)?sh|busybox")


def _sd_git_sub(vals):
    """The subcommand of a git call after its global options; None when a global option is not plain."""
    k = 0
    while k < len(vals) and vals[k].startswith("-"):
        if vals[k] == "-C" and k + 1 < len(vals):
            k += 2
            continue
        if vals[k] not in _SD_GIT_GLOBAL_FLAGS:
            return None
        k += 1
    return vals[k] if k < len(vals) else None


def _sd_traces(sites):
    """True when the shell may trace or echo the commands it runs: set -x/-v (or -o xtrace/verbose, shopt -o), a
    shell run with -x/-v, or a variable that turns tracing on or moves it."""
    from lib.shell_parse import resolve
    for site in sites:
        cmd = site.cmd
        texts = [a.word.text for a in cmd.assignments]
        try:
            res = resolve(cmd)
        except Exception:  # noqa: BLE001
            return True
        texts += [a.word.text for a in res.assignments]
        if any(re.match(r"['\"]?(SHELLOPTS|BASH_XTRACEFD|BASHOPTS)\+?=", t) for t in texts):
            return True
        name = (res.name or "").lower()
        if name in ("set", "shopt") or _SD_SHELL.fullmatch(name):
            for w in res.args:
                v = w.value()
                if v is None or v.lower() in ("xtrace", "verbose", "--verbose") or \
                        (re.fullmatch(r"[-+][A-Za-z]+", v) and set(v[1:]) & set("xv")):
                    return True
    return False


def _sd_reads_back(site, res):
    """Why this command can read an allowed mention's text back (the shell's command line, the commit message, the
    history, a process list), or None."""
    import fnmatch
    cmd = site.cmd
    words = [a.word for a in cmd.assignments] + list(cmd.words) + [r.target for r in cmd.redirects if r.target]
    for w in words:
        text = w.text
        for rx, base in _SD_DECODE:
            text = rx.sub(lambda m: chr(int(m.group(1), base) % 0x110000), text)
        text = re.sub(r"""['"\\]""", "", text.lower())
        if _SD_READBACK.search(text):
            return f"'{w.text}' can read the mention back"
        if any(p.kind != "lit" for p in w.parts):
            for comp in re.split(r"[/=:\s]", text):
                if any(c in comp for c in "*?[") and comp.strip("*?"):
                    if any(fnmatch.fnmatchcase(t, comp) for t in _SD_READBACK_GLOB):
                        return f"'{w.text}' can read the mention back"
    name = (res.name or "").lower() if res is not None else ""
    if name.rsplit("/", 1)[-1] in _SD_READBACK_PROGRAMS:
        return f"{name} can read the mention back"
    return None


# The whole command an allowed mention may stand in: a `;`/`&&`/`||` list (groups, subshells and `if` at most) of
# allowed search, log or commit calls and a few harmless commands, each with literal words, its output piped only
# into display filters and redirected only to /dev/null or between stdout and stderr. Nothing in it assigns or
# exports a variable, defines, configures or reads back anything, or writes a file.
_SD_PLAIN_WRAPPERS = frozenset({"timeout", "nice", "command"})
_SD_PLAIN_SHELLS = frozenset({"bash", "sh", "dash", "zsh", "ksh"})
_SD_PLAIN_GIT = frozenset({"status", "diff", "log", "show", "push", "fetch"})
# git options of those subcommands that run a program or write a file (taken in any abbreviation).
_SD_PLAIN_GIT_REFUSED = ("--ext-diff", "--textconv", "--receive-pack", "--upload-pack", "--exec")
_SD_PLAIN_COMPOUNDS = frozenset({"group", "subshell", "if"})


def _sd_quiet_redirects(redirects, stdin_doc=False):
    """True when every redirection sends stdout or stderr to /dev/null or to each other; a quoted heredoc or a
    literal here-string on stdin only where the call reads its message from it (stdin_doc)."""
    for r in redirects:
        if r.fd_var is not None:
            return False
        if r.op in ("<<", "<<-"):
            if not (stdin_doc and r.fd == 0 and r.hd is not None and (r.hd.quoted or not r.hd.expansions)):
                return False
            continue
        if r.op == "<<<":
            if not (stdin_doc and r.fd == 0 and r.target is not None and r.target.value() is not None
                    and all(p.kind == "lit" for p in r.target.parts)):
                return False
            continue
        if r.op == ">&" and r.dup is not None:
            if r.fd not in (1, 2) or r.dup not in (1, 2):
                return False
            continue
        if not r.writes() or r.target is None or r.target.value() != "/dev/null" or \
                any(p.kind != "lit" for p in r.target.parts):
            return False
    return True


def _sd_plain_git(vals):
    """True when a git call is status, diff, log, show, push or fetch with plain global options and nothing that
    runs a program or writes a file."""
    if _sd_git_sub(vals) not in _SD_PLAIN_GIT:
        return False
    for v in vals:
        name = v.partition("=")[0].lower()
        if _sd_writes_output(v) or (name.startswith("--") and len(name) >= 4 and
                                    any(r.startswith(name) for r in _SD_PLAIN_GIT_REFUSED)):
            return False
    return True


def _sd_plain_command(cmd):
    """True when one simple command fits the plain shape: an allowed search, log or commit call, or a harmless
    command (echo, printf, true, false, :, pwd, cd, ls, git status/diff/log/show/push/fetch), with plain wrappers at
    most, literal words and quiet redirections; or a shell -c or a find -exec whose code is itself plain."""
    from types import SimpleNamespace
    from lib.shell_parse import Script, resolve
    if cmd.assignments or not cmd.words:
        return False
    try:
        res = resolve(cmd)
    except Exception:  # noqa: BLE001
        return False
    if res.unresolved or res.assignments or res.head is None:
        return False
    if any(w[0] not in _SD_PLAIN_WRAPPERS for w in res.wrappers):
        return False
    hv = res.head.value()
    if hv is None or ("/" in hv and hv.rsplit("/", 1)[0] not in _SD_HEAD_DIRS):
        return False
    literal = all(w.value() is not None and all(p.kind == "lit" for p in w.parts) for w in cmd.words)
    name = res.name
    if res.payload is None and _sd_allowed(SimpleNamespace(cmd=cmd, templated=False)):
        commit = name == "git" and _sd_git_sub([w.value() or "" for w in res.args]) == "commit"
        return (literal or commit) and _sd_quiet_redirects(cmd.redirects, stdin_doc=commit)
    if not literal or not _sd_quiet_redirects(cmd.redirects):
        return False
    vals = [w.value() for w in res.args]
    if name in _SD_PLAIN_SHELLS:
        return len(vals) == 2 and vals[0] == "-c" and isinstance(res.payload, Script) and \
            _sd_plain_script(res.payload)
    if name == "find":
        actions = [v for v in vals if v in _SD_FIND_ACTIONS]
        return set(actions) <= {"-exec", "-execdir"} and len(actions) <= 1 and \
            (not actions or (isinstance(res.payload, Script) and _sd_plain_script(res.payload)))
    if res.payload is not None:
        return False
    if name in ("echo", "true", "false", ":", "pwd", "ls", "cd"):
        return True
    if name == "printf":
        return bool(vals) and vals[0] != "-v"
    return name == "git" and _sd_plain_git(vals)


def _sd_plain_script(script):
    """True when every command of a parsed list fits the plain shape (see _sd_plain_command): no background job,
    no loop, function, case or coproc, and every later pipeline stage a display filter with quiet redirections."""
    from lib.shell_parse import Compound, SimpleCommand
    if script.error is not None:
        return False
    for pl, sep in script.items:
        if sep == "&" or any(p not in ("|", "|&") for p in pl.pipes):
            return False
        for k, st in enumerate(pl.stages):
            if k > 0:
                if not (_sd_display(st) and _sd_quiet_redirects(st.redirects)):
                    return False
            elif isinstance(st, Compound):
                if st.kind not in _SD_PLAIN_COMPOUNDS or st.header or not _sd_quiet_redirects(st.redirects) or \
                        not all(_sd_plain_script(b) for b in st.body):
                    return False
            elif not (isinstance(st, SimpleCommand) and _sd_plain_command(st)):
                return False
    return True


def session_dirs_rule(command):
    """session_dirs.txt is never read, written or executed: its name may stand only as the pattern of grep, rg or
    git grep, the -S/-G/--grep value of git log, or a git commit message, only when the whole command is plain (see
    _sd_plain_script: literal words, no variable, configuration or file write, quiet redirections), and only while
    what that call prints reaches the terminal (through display filters at most) and no later word can reuse its
    last argument. Every
    other mention, a glob or expansion written to land on the file where a program reads, writes or runs it, a glob
    a program applies to names itself (find -name with an action, rg -g, grep --include, git pathspecs, tar, rsync)
    that matches it, and interpreter code naming it are refused; a call the parser cannot read keeps every mention
    refused."""
    low = sd_normalize(command)
    if not any(f in low for f in SD_FRAGMENTS):
        return
    from lib.shell_parse import parse, walk, resolve
    raw = list(command)
    reason = None
    try:
        script = parse(command)
        broken = bool(script.errors())
        sites = list(walk(script))
        streams = _sd_output_safety(script, _sd_traces(sites)) if not broken else {}
        plain = not broken and _sd_plain_script(script)
    except Exception:  # noqa: BLE001
        broken, sites, streams, plain = True, [], {}, False
    redefined = _SD_FUNCTION.search(low) is not None or any(_sd_redefines(site) for site in sites)
    env = _sd_env(sites)
    blank, others, committed, mentioned = [], [], False, False
    for site in sites if not broken else ():
        cmd = site.cmd
        key = _sd_key(site.context, cmd)
        out_safe = streams.get(key, (False, False))[0]
        allowed = [] if redefined or not out_safe or not plain else _sd_allowed(site)
        allowed_ids = {id(src) for src in allowed}
        try:
            res = resolve(cmd)
            name = res.name.lower() if res.name is not None else None
        except Exception:  # noqa: BLE001
            res, name = None, None
        lister = (out_safe and res is not None and res.payload is None and name in _SD_LISTERS
                  and not (name == "printf" and any(w.value() in (None, "-v") for w in res.args[:1]))
                  and not (name == "find" and any(w.value() in _SD_FIND_ACTIONS for w in res.args)))
        words = [a.word for a in cmd.assignments] + ([] if lister else list(cmd.words))
        words += [r.target for r in cmd.redirects if r.target]
        for w in words:
            if id(w.raw) not in allowed_ids and _sd_glob_hit(w, env):
                reason = f"'{w.text}' can resolve to {SD_NAME}"
        if res is not None and name is not None:
            hit = _sd_glob_operand(res, out_safe)
            if hit is not None:
                reason = f"the pattern '{hit}' {name} applies to file names matches {SD_NAME}"
        if res is None:
            code = [w.value() or w.text for w in cmd.words[1:]] + [r.hd.body for r in cmd.redirects if r.hd]
        elif name is not None and _SD_INTERPRETER.fullmatch(name):
            code = _sd_interpreter_code(res, cmd)
        else:
            code = []
        if any(_sd_code_names(c) for c in code):
            reason = f"interpreter code names {SD_NAME}"
        if site.depth == 0 or site.script.depth > 0:  # its offsets are the command's own
            blank += allowed
        if allowed:
            mentioned = True
            committed = committed or _sd_git_sub([w.value() or "" for w in res.args]) == "commit"
        else:
            others.append((site, res, name, streams.get(key, (False, False))))
    for site, res, name, (o, e) in others if mentioned else ():
        why = _sd_reads_back(site, res)
        if why is None and committed and name == "git":
            vals = [w.value() or w.text for w in res.args]
            sub = _sd_git_sub(vals)
            if any(_sd_writes_output(v) for v in vals) or (sub not in _SD_GIT_QUIET and not (o and e)):
                why = "a git call after the commit hands its message on"
        if why is not None:
            reason = f"{why} after {SD_NAME} is named"
    if blank and _SD_LAST_ARG.search(command):
        reason = f"a word reuses an earlier command's last argument after {SD_NAME} is named"
    for src in blank:
        pos = [(src.idx[i], ch) for i, ch in enumerate(src.text)]
        if all(0 <= j < len(raw) and command[j] == ch for j, ch in pos):
            for j, _ch in pos:
                raw[j] = "\x01"
    if reason is None and SD_NAME in sd_normalize("".join(raw)):
        reason = f"{SD_NAME} stands where it is read, written or run"
    if reason is None and broken and re.search(r"(sess|dirs)[^\s;&|]*([*?\[]|\{[^}\s]*,)|([*?\[]|\{[^}\s]*,)[^\s;&|]*"
                                                r"(sess|dirs)", command.lower()):
        reason = f"the command cannot be parsed and a glob in it can resolve to {SD_NAME}"
    if reason:
        refuse(f"BLOCKED: {SD_NAME} is never read, written or executed by an agent", f"Command: {command}",
               f"REASON: {reason}. Editing it once triggered a full session restore that killed every session.",
               "Allowed: the name as the pattern of grep, rg or git grep, as the -S/-G/--grep value of git log, or "
               "in a git commit message, with the output shown, not consumed. This refusal runs before /do and "
               "/allow; neither releases it.")


# ── Entry ────────────────────────────────────────────────────────────────────

def environment():
    tmp = os.environ.get("CLAUDE_TMPDIR") or os.environ.get("TMPDIR") or "/tmp"
    helper = os.environ.get("CLAUDE_DAEMON_RESTART_GRANT_HELPER", "")
    return {
        "prefix": os.environ.get("CLAUDE_PROTECTED_DAEMON_PREFIX", ""),
        "targets": os.environ.get("CLAUDE_PROTECTED_DAEMON_TARGETS", ""),
        "family": os.environ.get("CLAUDE_PROTECTED_PROCESS_FAMILY", ""),
        "dev_systemd": os.environ.get("CLAUDE_DEV_SYSTEMD", ""),
        "grant_dir": os.environ.get("CLAUDE_DAEMON_RESTART_GRANT_DIR") or tmp,
        "grant_hint": helper or "<daemon-restart grant helper>",
    }


def decide(payload_text):
    """The verdict token, or a refusal (refuse() exits 2)."""
    try:
        payload = json.loads(payload_text)
    except ValueError:
        payload = None
    get = payload.get if isinstance(payload, dict) else (lambda *a: None)
    if get("tool_name") != "Bash":
        return "ALLOW"
    try:
        command = str(payload.get("tool_input", {}).get("command", "")).rstrip("\n")
    except AttributeError:
        command = ""
    home = os.path.dirname(HOOKS)
    runtime_guard(payload_text, command)
    run_commit_guard(payload, command, home)
    consent_flag_rule(command, payload)
    session_dirs_rule(command)

    from lib.allowlist import has_do_consent, match_sentinel_grant_for_bash_command
    if not get("agent_id"):
        try:
            if has_do_consent(payload):
                return "CONSENT"
        except Exception:  # noqa: BLE001
            pass
    task = os.environ.get("CLAUDE_TASK_ID") or str(get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default"))
    if task:
        try:
            if match_sentinel_grant_for_bash_command(task, command) is not None:
                return "SENTINEL " + task
        except Exception:  # noqa: BLE001
            pass

    env = environment()
    daemon_rules(command, payload, env)
    commit_artifact_rules(command, state_dir())
    view = GitView(command)
    bulk_sentinel_rule(command)
    hard_ban_rule(command)
    executable = executable_view_or_raw(command)
    service_rules(command, executable, env)
    removal_policy(payload_text, command)
    kill_pid_rule(command, executable)
    worktree_git_rules(command, view)
    git_clean_rule(command, executable, view)
    return "ALLOW"


def main():
    """Stdout carries only the verdict: anything a library prints while the rules run goes to /dev/null."""
    verdict_out = os.fdopen(os.dup(1), "w")
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    sys.stdout = open(os.devnull, "w")
    verdict = decide(sys.stdin.read())
    verdict_out.write(verdict + "\n")
    verdict_out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
