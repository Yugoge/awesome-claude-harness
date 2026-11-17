#!/usr/bin/env python3
"""The rules of hooks/pretool-bash-safety.sh, one predicate each, run in one interpreter.

Usage: bash_safety_rules.py <hooks dir>  (the PreToolUse payload on stdin)

Exits 2 on a refusal, its message on stderr; otherwise prints ALLOW, CONSENT (main-agent /do consent) or
SENTINEL <task id> (a structured /allow grant). The shell entry allows CONSENT and SENTINEL after the pre-clean
snapshot guard and refuses anything else (no token, a crash, a wrong interpreter). The runtime and commit guards
run before the /do and /allow releases and neither releases them; every later rule is released by both. A view
that cannot be built degrades to the raw command, so a broken helper refuses more, never less.
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
    an option such as git's `-c` merely configures."""
    configured = os.environ.get("CLAUDE_HARD_BANNED_SCRIPTS", "")
    value = (configured or "session-recovery|restart-all-sessions").split("\n", 1)[0]
    bans = value.split("|")
    if bans and bans[-1] == "":
        bans.pop()
    data = None
    view = None
    for ban in bans:
        if configured:
            rx = ban
        else:
            rx = _HB_CMD + ban + r"""(\.sh)?(["'\s;&|)<>`]|$)"""
            if data is None and grep(rx, command):
                try:
                    masked = hard_ban_mask(command).rstrip("\n")
                except Exception:  # noqa: BLE001
                    masked = ""
                data = masked or command
        if ban and not configured and view is None:
            view = executable_view_or_raw(command)
        if ban and (grep(rx, data if data is not None else command) or (not configured and grep(rx, view))):
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
#
# The rules judge the git invocations lib/shell_parse.py finds where they run: past wrappers (sudo, env, xargs,
# nohup, timeout, a path-qualified git ...), inside shell payloads (bash -c, eval, a heredoc or pipe fed to a
# shell, find -exec, a git alias body) and, where interpreter code hands a string to a process-spawning call,
# inside that string. A git subcommand named in data (a grep pattern, an echo, a commit message, a heredoc a
# non-shell reads) is no invocation. That reading overrules a base refusal (raw-text patterns, classifier view) only
# when the whole command is the strict data shape (data_shape); anywhere else the verdict is the union of both, and
# a command the parser cannot read takes the base pass alone.

_INTERP_CODE_OPTS = (  # interpreter name pattern, the options whose value is the code, options taking a value
    (re.compile(r"^(python|pypy)[\d.]*$"), ("-c",), ("-W", "-X")),
    (re.compile(r"^(node|nodejs|bun|deno)[\d.]*$"), ("-e", "--eval", "-p", "--print"),
     ("-r", "--require", "--import", "--loader", "--experimental-loader", "--input-type", "--env-file")),
    (re.compile(r"^perl[\d.]*$"), ("-e", "-E"), ("-I", "-M", "-m")),
    (re.compile(r"^ruby[\d.]*$"), ("-e",), ("-I", "-r")),
    (re.compile(r"^php[\d.]*$"), ("-r",), ("-c", "-d")),
)
_SPAWN_RE = re.compile(r"\b(system|popen\w*|Popen|spawn\w*|exec\w*|run|call|check_call|check_output|getoutput|"
                       r"getstatusoutput|subprocess|child_process|shell_exec|passthru|proc_open|pcntl_exec|qx)\b|`")
_STR_LIT_RE = re.compile(r"'''(.*?)'''|\"\"\"(.*?)\"\"\"|'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"|`([^`]*)`",
                         re.S)
_VISIBLE = {"top", "cmdsub", "backtick", "procsub"}


def _interpreter_code(res, cmd):
    """The code an interpreter command runs from its own arguments (`-c CODE`, `-cCODE`, a cluster ending in the
    code option, `--eval=CODE`) or, with no script operand, from a heredoc or here-string; None if none."""
    name = res.name or ""
    spec = next(((c, v) for rx, c, v in _INTERP_CODE_OPTS if rx.match(name)), None)
    if spec is None:
        return None
    code_opts, value_opts = spec
    args = res.argv()
    k = 0
    while k < len(args):
        a = args[k]
        if a is None:
            k += 1
            continue
        if a in code_opts:
            return args[k + 1] if k + 1 < len(args) else None
        for o in code_opts:
            if o.startswith("--") and a.startswith(o + "="):
                return a[len(o) + 1:]
            if not o.startswith("--") and a.startswith(o) and len(a) > 2:
                return a[2:]
            if not o.startswith("--") and a.startswith("-") and not a.startswith("--") and len(a) > 2 \
                    and a[-1] == o[1] and a[1:-1].isalpha():
                return args[k + 1] if k + 1 < len(args) else None
        if a in value_opts:
            k += 2
            continue
        if a == "--" or a == "-" or not a.startswith("-"):
            break
        k += 1
    if all(a is None or a == "-" or a.startswith("-") for a in args):
        for red in cmd.redirects:
            if red.hd is not None and red.fd == 0:
                return red.hd.body
            if red.op == "<<<" and red.target is not None:
                return red.target.value()
    return None


def _interpreter_shell_texts(code):
    """Shell texts interpreter code hands to a process-spawning call: each string literal, and each comma-joined
    run of literals (an argv list) read as words. Code with no spawning call yields none."""
    if not code or "git" not in code or not _SPAWN_RE.search(code):
        return []
    lits = [(m.start(), m.end(), next(g for g in m.groups() if g is not None)) for m in _STR_LIT_RE.finditer(code)]
    texts, run, prev_end = [], [], None
    for a, b, body in lits:
        if run and not re.fullmatch(r"\s*,\s*", code[prev_end:a]):
            texts.append(" ".join(run))
            run = []
        run.append(body)
        prev_end = b
        texts.append(body)
    if run:
        texts.append(" ".join(run))
    return [t for t in dict.fromkeys(texts) if "git" in t]


# The strict data shape: the one place the working-tree rules let the invocation view overrule a base refusal.
_PIPE_FILTERS = frozenset({"head", "tail", "wc", "sort", "uniq", "cut", "less", "more", "grep", "rg"})
_SHAPE_SEARCHERS = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack"})
_SHAPE_COMMANDS = frozenset({"echo", "printf", "cat", "ls", "true", "git"}) | _SHAPE_SEARCHERS
_SAFE_DEVICES = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/1", "/dev/fd/2"})
_SHAPE_GIT_SUBS = frozenset({"status", "show", "diff", "log", "restore", "add", "commit", "rev-parse", "ls-files",
                             "stash", "checkout", "clean", "blame", "shortlog", "describe", "branch", "switch",
                             "cat-file", "ls-tree", "merge-base", "reflog", "tag"})
_SHAPE_GIT_GLOBALS = frozenset({"-C", "--no-pager", "-P", "--no-optional-locks"})
_EXEC_DOC_EXT_RE = re.compile(r"\.(sh|bash|zsh|ksh|fish|csh|tcsh|command|mk|mak|make|py|pl|pm|rb|js|mjs|cjs|ts|php|"
                              r"tcl|lua|awk|sed|ps1|bat|cmd|service|timer|desktop|cron|rc|env|envrc)$", re.I)
_EXEC_DOC_NAMES = frozenset({"makefile", "gnumakefile", "crontab", ".bashrc", ".bash_profile", ".bash_login",
                             ".bash_logout", ".profile", ".zshrc", ".zshenv", ".zprofile", ".zlogin", ".zlogout",
                             ".kshrc", ".cshrc", ".tcshrc", ".login", ".logout", ".envrc", ".inputrc", "config.fish",
                             "justfile", "rakefile", "dockerfile", "procfile", ".tclshrc"})


_HOOK_NAME_RE = re.compile(r"^(pre-|post-|p4-)|^(commit-msg|prepare-commit-msg|applypatch-msg|update|proc-receive|"
                           r"reference-transaction|push-to-checkout|sendemail-validate|fsmonitor-watchman)$")
_ROOT_CONFIG_EXT_RE = re.compile(r"\.(json|ya?ml|toml|ini|cfg|conf)$")


def _doc_path_ok(path):
    """A file the data shape may write: a relative literal path inside the repository that no shell, make, cron,
    git, hook manager or login sequence reads. Refused: an absolute path or one with a `..`, `~` or option form,
    any dot-file or dot-directory component (.git, .husky, .github, .vscode, .config, .pre-commit-config.yaml ...),
    a file named like a git hook, package.json, a json/yaml/toml/ini/cfg/conf file at the repository root, a file
    named config or *gitconfig*, any component ending in .git (a bare repository), and an executable or login-read
    name."""
    if not path or path.startswith(("~", "-", "/")):
        return False
    low = path.lower()
    parts = [c for c in low.split("/") if c not in ("", ".")]
    if not parts or any(c == ".." or c.startswith(".") or c.endswith(".git") for c in parts):
        return False
    base = parts[-1]
    if _HOOK_NAME_RE.search(base) or base in ("package.json", "config") or "gitconfig" in base \
            or (len(parts) == 1 and _ROOT_CONFIG_EXT_RE.search(base)):
        return False
    return not (base in _EXEC_DOC_NAMES or _EXEC_DOC_EXT_RE.search(base) or "bin" in parts
                or any(k in low for k in ("hook", "cron", "systemd", "autostart", "profile.d", "rc.d", "init.d")))


def _long_prefix_of(arg, names, shortest=3):
    """True when `arg` (before any `=`) is `--x` with x a prefix, at least `shortest` characters with the dashes,
    of one of `names` (git and GNU tools take any unique abbreviation of a long option)."""
    name = (arg or "").split("=", 1)[0]
    return name.startswith("--") and len(name) >= shortest and any(n.startswith(name) for n in names)


def _word_is_static(w):
    return all(p.kind not in ("cmdsub", "backtick", "procsub_in", "procsub_out") for p in w.parts)


def _shape_redirects(cmd, may_write_doc, state):
    for red in cmd.redirects:
        if red.fd_var is not None:
            return False
        if red.hd is not None:
            if red.hd.expansions:
                return False
            continue
        if red.target is not None and not _word_is_static(red.target):
            return False
        if red.writes():
            lit = red.target.literal() if red.target is not None else None
            if lit not in _SAFE_DEVICES and not (may_write_doc and _doc_path_ok(lit)):
                return False
            if lit not in _SAFE_DEVICES:
                state["writes"] = True
    return True


def _shape_git(cmd, invs):
    mine = [(i, ctx) for i, ctx in invs if i.cmd is not None and i.cmd.span == cmd.span and ctx == ("top",)]
    if len(mine) != 1:
        return False
    inv, ctx = mine[0]
    if inv.alias_body is not None or inv.unresolved or inv.config_pairs or inv.env \
            or inv.path_qualified or inv.subcommand not in _SHAPE_GIT_SUBS \
            or any(opt not in _SHAPE_GIT_GLOBALS for opt, _v in inv.global_opts):
        return False
    if any(a is None for a in inv.args):
        return False  # a glob or expansion (`-- *`, `$x`) the view cannot read: the base verdict stands
    args = list(inv.args)
    if any(_long_prefix_of(a, ("--output",)) for a in args):
        return False  # git writes the named file (log, show, diff, reflog ... --output / --outp / --ou)
    return "--ext-diff" not in args


def _uniq_writes(args):
    """uniq given an output operand (its second file operand) writes that file."""
    operands, k, opts_done = 0, 0, False
    while k < len(args):
        a = args[k]
        if opts_done or a == "-" or not a.startswith("-"):
            operands += 1
        elif a == "--":
            opts_done = True
        elif a in ("-f", "-s", "-w") or (a.startswith("--") and "=" not in a and _long_prefix_of(
                a, ("--skip-fields", "--skip-chars", "--check-chars"), 4)):
            k += 1
        k += 1
    return operands >= 2


_ACK_AG_SHORT = frozenset("iIsSvwlLcnhHQFk1")
_ACK_AG_LONG = frozenset({"--ignore-case", "--smart-case", "--case-sensitive", "--invert-match", "--word-regexp",
                          "--literal", "--count", "--files-with-matches", "--files-without-matches", "--nocolor",
                          "--no-color", "--color", "--noheading", "--no-heading", "--heading", "--nogroup",
                          "--no-group", "--group", "--column", "--nopager", "--noenv", "--no-filename",
                          "--with-filename", "--ignore-dir", "--type"})


def _ack_ag_options_ok(args):
    """Every option of an ack or ag word list is on a small allow-list: short clusters of plain matching flags,
    -A/-B/-C with a number, and exact long names (with an `=value` only for --ignore-dir and --type). Any other
    option (a --pager / --ackrc abbreviation, --search-zip, -z ...) leaves the data shape."""
    for a in args:
        if a == "--":
            return True
        if not a.startswith("-") or a == "-":
            continue
        if a.startswith("--"):
            name, eq, _val = a.partition("=")
            if name not in _ACK_AG_LONG or (eq and name not in ("--ignore-dir", "--type")):
                return False
        elif not (all(c in _ACK_AG_SHORT for c in a[1:]) or re.fullmatch(r"-[ABC]\d*", a)):
            return False
    return True


def _shape_simple(cmd, invs, stage, state):
    """One simple command of the data shape: a pipeline's first stage, or a later pure-filter stage."""
    from lib.shell_parse import SimpleCommand, resolve
    if not isinstance(cmd, SimpleCommand) or cmd.assignments or not cmd.words \
            or not all(_word_is_static(w) for w in cmd.words):
        return False
    head = cmd.words[0].literal()
    if head is None or "/" in head:
        return False
    res = resolve(cmd)
    if res.wrappers or res.payload is not None or res.unresolved or res.head is not cmd.words[0]:
        return False
    name = res.name
    if name not in (_PIPE_FILTERS if stage else _SHAPE_COMMANDS):
        return False
    args = [w.value() or "" for w in cmd.words[1:]]
    if name == "printf" and any(a.startswith("-v") for a in args):
        return False
    if name in _SHAPE_SEARCHERS and any(a.startswith(("--pre", "--pager", "--hostname-bin", "--search-zip"))
                                         or (name == "rg" and a.startswith("-") and not a.startswith("--")
                                             and "z" in a) for a in args):
        return False
    if name in ("ack", "ag") and not _ack_ag_options_ok(args):
        return False  # ack/ag take any unique abbreviation (--pag=, --pa, --ackr=): only listed options stay inside
    if name == "sort" and any(_long_prefix_of(a, ("--output", "--compress-program"))
                              or (a.startswith("-") and not a.startswith("--") and "o" in a) for a in args):
        return False  # -o / -uoFILE / --output / --outp= / --o write a file; --compress-program runs one
    if name == "uniq" and _uniq_writes(args):
        return False
    if name == "git":
        if not _shape_git(cmd, invs):
            return False
        state["git"] = True
    return _shape_redirects(cmd, may_write_doc=(name == "cat" and not stage), state=state)


def data_shape(command, invs):
    """True when the whole command is the strict data shape, where the invocation view's verdict stands alone.

    It parses cleanly into a `;` / `&&` / `||` list (nothing in the background) of pipelines. A first stage is
    echo or printf (no -v), grep or rg (no --pre, --pager, --hostname-bin, decompression), ag or ack with listed
    options only (_ack_ag_options_ok), cat, ls, true, or a plain git invocation (every argument a literal) of a fixed
    subcommand set (no alias, -c, GIT_* assignment, wrapper, path-qualified git,
    exec-taking option); a later stage is only a pure filter (head, tail, wc, sort, uniq, cut, less, more, grep, rg).
    Output goes to stdout or a device only, except that cat may write a document path no shell, make, cron, git or
    login sequence reads (_doc_path_ok); a command that writes any file runs no git at all, so no hook it could
    plant fires. No git option, sort or uniq form writes a file. No word holds a command or process substitution and
    no heredoc body expands. So no shell, interpreter, xargs, tee, at, batch, crontab, make, git hook or unknown
    program ever runs what the command prints or writes."""
    if invs is None:
        return False
    try:
        from lib.shell_parse import parse
        script = parse(command)
        if script.error is not None or script.errors() or not script.items:
            return False
        state = {"writes": False, "git": False}
        for pipeline, sep in script.items:
            if sep not in (None, "", ";", "&&", "||", "\n") or any(p not in ("|", "|&") for p in pipeline.pipes):
                return False
            if not all(_shape_simple(stage, invs, k, state) for k, stage in enumerate(pipeline.stages)):
                return False
        return not (state["writes"] and state["git"])
    except Exception:  # noqa: BLE001 - anything unexpected is outside the shape
        return False


def _grep_pager_texts(args):
    """The pager commands a `git grep` runs on its matches: the value of --open-files-in-pager=CMD or of any `--o...`
    abbreviation of it, and the rest of a short cluster after its O (-OCMD, -iOCMD)."""
    texts = []
    for a in args:
        if a is None or a == "--":
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if eq and val and _long_prefix_of(name, ("--open-files-in-pager",)):
                texts.append(val)
        elif a.startswith("-") and "O" in a[1:]:
            val = a[a.index("O", 1) + 1:]
            if val:
                texts.append(val)
    return texts


def git_view(command):
    """[(GitInvocation, context)] for every git invocation the command runs, or None when it does not parse.

    context is the walk's context tuple; a git alias body adds "alias", interpreter code adds "interp".
    """
    if "git" not in command:
        return []
    try:
        from lib.shell_parse import parse, git_invocations, walk, resolve
        into = ("cmdsub", "backtick", "procsub", "heredoc_shell", "pipe_shell", "shell_c", "eval", "exec_argv")
        script = parse(command)
        if script.error is not None:
            return None
        out = []

        def collect(scr, prefix, depth):
            for inv in git_invocations(scr, into=into):
                ctx = prefix + tuple(inv.context[1:])
                out.append((inv, ctx))
                if inv.alias_body is not None and depth < 8:
                    collect(inv.alias_body, ctx + ("alias",), depth + 1)
                if inv.subcommand == "grep" and depth < 4:
                    for text in _grep_pager_texts(inv.args):
                        sub = parse(text)
                        if sub.error is None:
                            collect(sub, ctx + ("pager",), depth + 1)
            if depth >= 4:
                return
            for site in walk(scr, into=into):
                res = resolve(site.cmd)
                for text in _interpreter_shell_texts(_interpreter_code(res, site.cmd)):
                    sub = parse(text)
                    if sub.error is None:
                        collect(sub, prefix + tuple(site.context[1:]) + ("interp",), depth + 1)

        collect(script, ("top",), 0)
        return out
    except Exception:  # noqa: BLE001 - an unreadable command takes the raw-text fallback
        return None


def _wide_path_after_dashdash(args):
    try:
        dd = args.index("--")
    except ValueError:
        return False
    path = args[dd + 1] if dd + 1 < len(args) else ""
    return path in (".", "*") or (path or "").endswith("/")


def _stash_pushes(args):
    bad = {"push", "save", "create", "store", "-u", "--include-untracked", "-a", "--all"}
    first = args[0] if args else None
    return first is not None and (first in bad or (
        first.startswith("-") and not first.startswith("--") and any(c in first[1:] for c in "ua")))


def _checkout_wide(args):
    """A wide path after `--` and any word before it: a ref (`HEAD -- .`) or an option alone (`--ours -- .`,
    `--theirs`, `-m`/`--merge`, `--conflict=...`, `-f`/`--force`, `-p`/`--patch`, `--no-overlay`,
    `--ignore-skip-worktree-bits` ...), each of which overwrites the working tree or its conflict resolutions.
    Only the plain `git checkout -- <wide path>` keeps the base verdict (allowed)."""
    if not _wide_path_after_dashdash(args):
        return False
    return len(args[:args.index("--")]) > 0


def _restore_wide_from_ref(args):
    """--source/-s given, the working tree among the targets (--worktree/-W, or no --staged/-S), a wide path."""
    if not _wide_path_after_dashdash(args):
        return False
    source = worktree = staged = False
    skip = False
    for a in args[:args.index("--")]:
        if skip or a is None:
            skip = False
            continue
        if a == "--source" or a.startswith("--source="):
            source, skip = True, a == "--source"
        elif a == "--worktree":
            worktree = True
        elif a == "--staged":
            staged = True
        elif a.startswith("-") and not a.startswith("--"):
            for k, c in enumerate(a[1:]):
                if c == "s":
                    source, skip = True, k == len(a) - 2
                    break
                worktree, staged = worktree or c == "W", staged or c == "S"
    return source and (worktree or not staged)


# Git global options the quote-neutralised worktree pass reads between git and the subcommand.
_WORKTREE_GOPT_MAX = 32


def _worktree_raw_fallback(command, globals_=False):
    """The pre-parser patterns, for a command lib/shell_parse.py cannot read (fail closed). With globals_ (the
    quote-neutralised pass over a payload the parser may not read), git global options and their values
    (-C x, -c k=v, --git-dir=..., --no-pager ...) may stand between git and the subcommand, per the GC_GOPT grammar.
    There `git` must start a word (command position, as in GIT_CLEAN_OCCURRENCE_RE) and the option run is bounded,
    so a long run of option words holding `git` (-Pgit, a=bgit, -C git) is scanned in linear time, not quadratic."""
    if globals_:
        g = rf"(^|{GC_SEP}){GC_GIT}{GC_GOPT.removesuffix('*')}{{0,{_WORKTREE_GOPT_MAX}}}\s+"
        if not grep(g + r"(stash|checkout|restore)\b", command):  # one bounded scan before the per-form ones
            return {"push": False, "bare": False, "checkout": False, "restore": False}
    else:
        g = r"git\s+"
    return {
        "push": grep(g + r"stash\s+(push|save|create|store|-u|--include-untracked|-a|--all)\b", command)
        or grep(g + r"stash\s+-[ua]+\b", command),
        "bare": grep(g + r"stash\s*($|[;&|])", command),
        "checkout": grep(g + r"checkout\s+\S+\s+--\s+(\.|\*|[^ ]+/)\s*($|[;&|])", command),
        "restore": grep(g + r"restore\b", command) and grep(r"(--source\b|-s\b)", command)
        and grep(r"--\s+(\.|\*|[^ /]+/)\s*($|[;&|])", command),
    }


def _worktree_base_hits(command, view):
    """The base pass: the raw-text patterns OR the classifier view's outer invocations."""
    hit = _worktree_raw_fallback(command)
    first = (view.outer("stash") or [None])[0]
    hit["push"] = hit["push"] or (first is not None and (not first["args"] or _stash_pushes(first["args"])))
    hit["bare"] = hit["bare"] or any(not i["args"] for i in view.outer("stash"))
    hit["checkout"] = hit["checkout"] or any(_wide_path_after_dashdash(i["args"]) for i in view.outer("checkout"))
    hit["restore"] = hit["restore"] or any(
        any(a in ("--source", "-s") or a.startswith(("--source=", "-s=")) for a in i["args"])
        and _wide_path_after_dashdash(i["args"]) for i in view.outer("restore"))
    return hit


def worktree_git_rules(command, invs, view=None, shape=False):
    """git stash (push forms and bare), wide-path checkout and restore from a ref.

    The invocation view refuses what it finds running. Unless the whole command is the strict data shape
    (data_shape), a raw-text pattern over the command's code text that no invocation accounts for still refuses,
    and so does every base refusal (raw-text patterns, classifier view): outside that shape no base refusal is lost.
    A command the parser cannot read takes the base pass alone."""
    if invs is None:
        hit = _worktree_base_hits(command, view) if view is not None else _worktree_raw_fallback(command)
    else:
        def args_of(sub):
            return [list(i.args) for i, _ctx in invs if i.subcommand == sub]
        hit = {"push": any(_stash_pushes(a) for a in args_of("stash")),
               "bare": any(not a for a in args_of("stash")),
               "checkout": any(_checkout_wide(a) for a in args_of("checkout")),
               "restore": any(_restore_wide_from_ref(a) for a in args_of("restore"))}
        if not shape:
            code = code_text(command)
            unaccounted = _worktree_raw_fallback(code)
            if grep(GC_SHELL_RE + "|" + GC_EXECCTX_RE, code):
                # A shell (any word ending in sh: fish, csh ...) or an exec-taking git subcommand in command position
                # runs a quoted string the parser may not read as one: match with the quotes neutralised, and a bare
                # stash found only there (inside quotes) counts as a push, as the base view counts a nested bare stash.
                quoted = _worktree_raw_fallback(code.replace('"', " ").replace("'", " "), globals_=True)
                quoted["push"] = quoted["push"] or (quoted["bare"] and not unaccounted["bare"])
                unaccounted = {k: unaccounted[k] or quoted[k] for k in unaccounted}
            base = _worktree_base_hits(command, view) if view is not None else _worktree_raw_fallback(command)
            hit = {k: hit[k] or unaccounted[k] or base[k] for k in hit}
    if hit["push"]:
        refuse("BLOCKED: 'git stash push/save/create/store/-u/--all' requires explicit user approval",
                   f"Command: {command}",
                   "REASON: a stash used as a throwaway buffer before a wide checkout can silently lose work; "
                   "-u/--include-untracked/-a/--all also take untracked and ignored files.",
                   "Tell the user what you want to do and ask them to run it, or use commit/branch.", released_line())
    if hit["bare"]:
        refuse("BLOCKED: bare 'git stash' (implicit push) requires explicit user approval", f"Command: {command}",
                   "Safe stash subcommands are exempt: list, show, pop, apply, drop, clear, branch.", released_line())
    if hit["checkout"]:
        refuse("BLOCKED: 'git checkout <ref> -- .' / '-- *' / '-- dir/' requires explicit user approval",
                   f"Command: {command}",
                   "REASON: a wide-path checkout from a commit overwrites a whole subtree with old content.",
                   "Allowed: 'git checkout <ref> -- path/to/specific-file.ts' (single file).",
                   "If you need a subtree restore, tell the user what you need and why.", released_line())
    if hit["restore"]:
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


_DATA_COMMANDS = frozenset({"echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "ack"})


def code_text(command):
    """The command with text no shell runs blanked, offsets kept: comments, the heredoc body of a command that is
    not a shell (unless the body expands something), and the all-literal arguments of a command that only prints
    or searches its arguments (echo, printf, grep ...). The raw command when it does not parse."""
    try:
        from lib.shell_parse import SHELLS, _blank, _blank_comments, parse, resolve, walk
        script = parse(command)
        if script.error is not None:
            return command
        out = list(command)
        _blank_comments(command, out)
        for site in walk(script, into=("cmdsub", "backtick", "procsub")):
            res = resolve(site.cmd)
            if res.name is None:
                continue
            for red in site.cmd.redirects:
                if red.hd is not None and res.name not in SHELLS and not red.hd.expansions:
                    _blank(out, *red.hd.body_span, keep_newlines=True)
            if res.name in _DATA_COMMANDS and not res.wrappers:
                for w in res.args:
                    if all(p.kind == "lit" for p in w.parts):
                        _blank(out, *w.span)
        return "".join(out)
    except Exception:  # noqa: BLE001
        return command


def git_clean_verdict(command, view):
    """ALLOW only for a provable dry run; BLOCK:nested / BLOCK:trust / BLOCK:exclude / BLOCK:dryrun otherwise.

    Trust first: every argument is written as a plain literal and read statically (T1), and no xargs injects
    arguments (T3). Then a separate-value exclude eats the next token, and the effective
    dry-run state is read up to the first `--`, last one wins, default off. It reads GitView (the base pass the
    working-tree rules union with the invocation view of git_clean_view_verdict).
    """
    from lib.shell_parse import resolve
    raw = [i for i in view.invs if i["subcommand"] == "clean"]
    # More `git … clean` occurrences than resolved invocations means one sits where the walk cannot see it. A clean
    # in a command or process substitution is where the walk sees it (and judged below), so it counts.
    if _clean_occurrences(command) > len([i for i in raw if set(i["git"].context) <= _VISIBLE]):
        return 'BLOCK:nested'
    for inv in raw:
        g = inv["git"]
        injected = g.cmd is not None and any(w[0] == "xargs" for w in resolve(g.cmd).wrappers)
        if injected or g.unresolved or None in g.args or not all(_CLEAN_LITERAL.match(w.text) for w in g.arg_words):
            return 'BLOCK:trust'
        verdict = _clean_args_verdict(inv["args"])
        if verdict != 'ALLOW':
            return verdict
    return 'ALLOW'


_CLEAN_LITERAL = re.compile(r'^[A-Za-z0-9_./=+:@,-]*$')


def _clean_occurrences(text):
    """How many `git … clean` occurrences the occurrence grammar finds, with quotes neutralised when a shell or an
    exec-taking git subcommand holds command position."""
    coarse, shell_cmd, exec_ctx = (re.compile(p) for p in (GIT_CLEAN_OCCURRENCE_RE, GC_SHELL_RE, GC_EXECCTX_RE))
    if shell_cmd.search(text) or exec_ctx.search(text):
        return max(len(coarse.findall(text.replace('"', q).replace("'", q))) for q in (' ', ''))
    return len(coarse.findall(text))


def _clean_args_verdict(args):
    """The exclude gate, then the effective dry-run state, over one clean invocation's arguments."""
    pos_dry = re.compile(r'^--d(r(y(-(r(u(n)?)?)?)?)?)?$')
    neg_dry = re.compile(r'^--no-d(r(y(-(r(u(n)?)?)?)?)?)?$')
    exclude = re.compile(r'^--e(x(c(l(u(d(e)?)?)?)?)?)?$')
    cluster = re.compile(r'^-[A-Za-z]+$')
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
    return 'ALLOW' if state else 'BLOCK:dryrun'


def git_clean_view_verdict(command, invs):
    """The verdict over lib/shell_parse.py's invocations; '' when the command runs no `git clean`.

    A clean inside a shell payload (bash -c, eval, a fed shell, find -exec, a git alias) is BLOCK:nested, as is a
    `git … clean` occurrence in the command's code text that no invocation accounts for (rebase -x, submodule
    foreach ...). A clean that interpreter code spawns, or one the command runs itself, passes only as a provable
    dry run: literal arguments, no argument-injecting xargs, no separate-value exclude, dry-run on.
    """
    if "clean" not in command:
        return ""
    from lib.shell_parse import resolve
    cleans = [(i, ctx) for i, ctx in invs if i.subcommand == "clean"]
    visible = [(i, ctx) for i, ctx in cleans if set(ctx) <= _VISIBLE]
    found = _clean_occurrences(code_text(command))
    if not cleans and not found:
        return ""
    if found > len(visible) or any(not set(ctx) <= _VISIBLE | {"interp"} for _i, ctx in cleans):
        return "BLOCK:nested"
    for inv, _ctx in cleans:
        res = resolve(inv.cmd) if inv.cmd is not None else None
        if inv.unresolved or any(a is None for a in inv.args) \
                or (res is not None and any(w[0] == "xargs" for w in res.wrappers)) \
                or not all(_CLEAN_LITERAL.match(w.text) for w in inv.arg_words):
            return "BLOCK:trust"
        verdict = _clean_args_verdict(list(inv.args))
        if verdict != "ALLOW":
            return verdict
    return "ALLOW"


def _git_clean_base(command, stripped, view):
    """The base pass over the raw text and the classifier view: (verdict, fail_closed); verdict '' when the
    classifier sees no clean."""
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
    fail_closed = not has_inv and bool(grep(GIT_CLEAN_OCCURRENCE_RE, command + "\n" + stripped + "\n" + probe))
    return verdict, fail_closed


def git_clean_rule(command, stripped, view, invs, shape=False):
    """BS-43: `git clean` passes only as a provable dry run. The invocations come from lib/shell_parse.py; a clean
    they do not account for (an exec-taking git subcommand, a launcher the parser does not read) is found by the
    occurrence grammar over the command's code text and fails closed. The base pass (raw text and classifier view)
    still refuses whatever it refuses unless the whole command is the strict data shape (data_shape) and runs no
    clean; a command the parser cannot read takes the base pass alone."""
    fail_closed = False
    verdict = ""
    if invs is not None:
        try:
            verdict = git_clean_view_verdict(command, invs)
        except Exception:  # noqa: BLE001
            verdict = "BLOCK:trust"
    # The shape lifts a base refusal only where no clean runs: a real clean beside a mention keeps the base count.
    lift = invs is not None and shape and not any(i.subcommand == "clean" for i, _ctx in invs)
    if verdict in ("", "ALLOW") and not lift:
        base_verdict, base_fc = _git_clean_base(command, stripped, view)
        if base_fc or base_verdict not in ("", "ALLOW"):
            verdict, fail_closed = ("" if base_fc else base_verdict), base_fc
    has_inv = bool(verdict)
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
    invs = git_view(command)
    shape = data_shape(command, invs)
    worktree_git_rules(command, invs, view, shape)
    git_clean_rule(command, executable, view, invs, shape)
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
