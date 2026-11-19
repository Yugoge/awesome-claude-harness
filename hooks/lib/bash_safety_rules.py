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
import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import time
import urllib.parse

HOOKS = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(HOOKS, "lib")
sys.path[:0] = [p for p in (HOOKS, LIB) if p not in sys.path]

from lib import git_facts  # noqa: E402
from lib.git_facts import GIT_DIR_CONFIG_FILES  # noqa: E402
from lib.shell_parse import GIT_GLOBAL_VALUE_OPTS, GIT_INERT_FLAGS, git_global_options, git_plain_subcommand_index  # noqa: E402
# A git option word that runs a program or writes a file: grep's -O, or one starting with a long option of
# git_facts.GIT_RUN_OR_WRITE_OPTIONS (`--output=x`, `--exec=...`).
_GIT_RUN_OR_WRITE_PREFIXES = ("-O",) + tuple(sorted(git_facts.GIT_RUN_OR_WRITE_OPTIONS))


PAYLOAD = ""  # the call's payload text (decide() sets it), for the refusal record


def refuse(*lines):
    """Refuse the call: the lines go to stderr, and the process exits 2, which the shell entry relays."""
    sys.stderr.write("".join(line + "\n" for line in lines))
    sys.stderr.flush()
    record("\n".join(lines))
    sys.exit(2)


def record(text, kind="refusal"):
    """A report of this call to the refusal record (lib/refusal_record.py): a refusal, or kind "unproven" for a
    command the removal policy lets through unproven. It never changes the verdict."""
    try:
        import refusal_record
        refusal_record.report(PAYLOAD, [(__file__, text)], __file__, kind)
    except Exception:  # noqa: BLE001
        pass


def released_line():
    return "Release: the user can authorize this command with /do or a matching /allow grant."

def lines_of(text):
    return text.split("\n")


def grep(pattern, text):
    """`grep -qE`: a match on any line of text."""
    rx = re.compile(pattern) if isinstance(pattern, str) else pattern
    return any(rx.search(line) for line in lines_of(text))


def state_dir():
    """The hook state root: its one resolution (lib/locations.state_root)."""
    return locations.state_root()


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


def _no_commit_or_config(command):
    """lib/shell_parse.py's reading of a command whose quoting the commit guard's own splitter cannot follow: True
    when it parses, no command word or payload is computed, no computed word spells git with commit or config, and
    every git invocation it runs or carries in a static string is read whole, sets no configuration and is neither
    commit nor config."""
    try:
        from lib.shell_parse import git_invocations, parse, walk
        script = parse(command)
        return not script.errors() and not any(
            s.dynamic or s.templated or any(w.value() is None and commit_guard_applies(w.text) for w in s.cmd.words)
            for s in walk(script)) and all(
            i.unresolved is None and i.subcommand not in (None, "commit", "config") and not (i.config_pairs or i.env)
            for i in git_invocations(script, strings=True))
    except Exception:  # noqa: BLE001
        return False


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
    LONGV = tuple(o[2:] for o in sorted(git_facts.GIT_COMMIT_VALUE_OPTIONS))
    GV = {'--git-dir': 'GIT_DIR', '--work-tree': 'GIT_WORK_TREE'}
    CFGW, CFGR = git_facts.GIT_CONFIG_WRITE_SUBCOMMANDS, git_facts.GIT_CONFIG_READ_SUBCOMMANDS
    WRF, RDF = git_facts.GIT_CONFIG_WRITE_OPTIONS, git_facts.GIT_CONFIG_READ_OPTIONS

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
            if k == 'd' and st[-1:] == ')' and '"' in st and re.search(r'(^|[\s;&|(])(-\w*c|eval)\s+"$', o) and gitish(t[i:]) \
                    and not _no_commit_or_config(d.get('tool_input', {}).get('command', '')):
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
        if b in COMMON_SHELLS and c:
            scan(t[c[0] + 1], depth + 1, lg, gc)
        if b in CD_TARGET_BUILTINS:
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
        # Literal refuse() calls, so the replay's site catalog (tests/replay/sites.py) reads the text.
        if bad:
            refuse(f"BLOCKED: unregistered-settings-filter — settings.json has local changes and the settings filter is "
                   f"not registered in {top}", f"Command: {command}", f"Run scripts/bootstrap in {top} first, then retry.",
                   f"settings.json is unusable: {bad}")
        refuse(f"BLOCKED: unregistered-settings-filter — settings.json has local changes and the settings filter is "
               f"not registered in {top}", f"Command: {command}", f"Run scripts/bootstrap in {top} first, then retry.")
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
            r.name in _core._SERVICE_MANAGER_PROGRAMS and any(a in verbs for a in r.argv())
            for r in (resolve(site.cmd) for site in walk(parse(command))))
    except Exception:  # noqa: BLE001 - the guard or the parser unavailable: the raw reading, which over-blocks
        return grep(r"systemctl\s+" + DAEMON_VERBS + r"(\s+|\b)", command) and grep(re.escape(prefix), command)


from lib import bash_read_only as _bash_read_only  # noqa: E402 -- the programs that only read

from lib.shell_parse import LOOPBACK_HOSTS  # noqa: E402 -- the host names that are this machine

LOOPBACK = "|".join(map(re.escape, LOOPBACK_HOSTS))
HTTP_STOP_URL = r"(?:%s):[0-9]+/stop(?![A-Za-z0-9])" % LOOPBACK
"""A localhost port's stop endpoint: `/stop`, `/stop?x`, `/stop/now`, `/stop-now`, `/stop_server`; never `/stops`
or `/stopwords`."""
HTTP_STOP_BARE_URL = r"(?:^|(?<=[\s'\"=])):[0-9]+/stop(?![A-Za-z0-9])"
"""httpie's shorthand for localhost (`:8080/stop`); it counts only in an HTTP client's own arguments."""
HTTP_STOP_ANY = r":[0-9]+/stop"
"""Any port's /stop prefix, whatever the host and whatever follows."""
HTTP_STOP_RAW_CLIENT = r"(curl|wget|nc\s|ncat|http\.client|aiohttp|requests)"
HTTP_STOP_RAW_URL = r"(localhost|127\.0\.0\.1):[0-9]+/stop"
"""The rule's raw reading: a client word anywhere in the text and a localhost /stop prefix anywhere."""
HTTP_CLIENTS = frozenset({"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "http", "https", "httpie",
                          "xh", "xhs"})
HTTP_INTERPRETERS = re.compile(r"^(i?python|pypy|node|nodejs|deno|bun|perl|ruby|php)[0-9.]*(-dbg)?$")
HTTP_LIBRARIES = r"(http\.client|aiohttp|requests|urllib|httpx|fetch\(|axios|LWP|HTTP::Tiny|Net::HTTP)"
HTTP_STOP_READERS = frozenset({"grep", "egrep", "fgrep", "rg", "echo", "printf", "cat", "sed", "git"})
"""Commands that only print the text they are given or read (sed, git and uniq under the checks of _http_reader_ok).
ag and ack are not readers: their `--pager` runs a command."""
HTTP_STOP_FILTERS = _bash_read_only.FILTERS  # the one list of text filters (lib/bash_read_only.py)
HTTP_STOP_CONTEXTS = frozenset({"top", "cmdsub", "backtick"})


def _http_sites(command):
    """[(site, resolved)] for every simple command the parser reaches, or None when the text does not parse."""
    try:
        from lib.shell_parse import SimpleCommand, parse, resolve, walk
        script = parse(command)
        if script.error is not None:
            return None
        out = []
        for site in walk(script):
            if not isinstance(site.cmd, SimpleCommand):
                return None
            out.append((site, resolve(site.cmd)))
        return out
    except Exception:  # noqa: BLE001 - the parser unavailable: the caller's raw reading
        return None


def _http_plain(site, r):
    """The literal command word of a simple command run as written: no wrapper, payload, prefix assignment or
    computed command word, at the top or inside a plain command substitution. Else None."""
    cmd = site.cmd
    if site.dynamic or cmd.assignments or not cmd.words or r.wrappers or r.payload is not None or r.unresolved:
        return None
    if not set(site.context) <= HTTP_STOP_CONTEXTS:
        return None
    head = cmd.words[0].value()
    if head is None:
        return None
    name = os.path.basename(head)
    return name if name == r.name else None


def _git_grep_pager(arg):
    """True if a `git grep` argument opens the matches in a pager it runs: `-O<cmd>`, a short cluster reaching `O`
    before a letter that takes a value (`-iO<cmd>`, `-nO`), or `--open-files-in-pager` in any abbreviation git
    accepts (`--op`, `--open=<cmd>`)."""
    if arg.startswith("--"):
        name = arg.split("=", 1)[0]
        return len(name) > 2 and "--open-files-in-pager".startswith(name) and name != "--"
    if arg.startswith("-") and len(arg) > 1:
        for ch in arg[1:]:
            if ch == "O":
                return True
            if ch in "ABCefm" or ch.isdigit():
                return False  # the rest of the cluster is this option's value
    return False


def _http_reader_ok(site, r):
    """True if the simple command only prints or filters text: a reader or a pure filter, as written, whose
    redirections write nowhere but /dev/null."""
    name = _http_plain(site, r)
    if name not in HTTP_STOP_READERS | HTTP_STOP_FILTERS:
        return False
    for rd in site.cmd.redirects:
        if rd.writes() and not (rd.target is not None and rd.target.value() == locations.NULL_DEVICE):
            return False
    args = [w.value() if w.value() is not None else w.text for w in site.cmd.words[1:]]
    if name in ("sed", "rg", "git") and any(w.value() is None for w in site.cmd.words[1:]):
        return False  # a computed operand could be a script, a preprocessor or an option
    if name == "rg" and any(a.startswith("--pre") for a in args):
        return False
    if name == "git":
        return bool(args) and args[0] in ("log", "show", "diff", "grep") and not any(
            a.startswith(_GIT_RUN_OR_WRITE_PREFIXES) for a in args) \
            and not (args[0] == "grep" and any(_git_grep_pager(a) for a in args[1:]))
    if name in ("uniq", "sort"):
        return _bash_read_only.reads_only(name, args)  # uniq IN OUT; sort -o, --compress-program
    if name == "sed":
        quiet, scripts, operands, take = False, [], [], False
        for a in args:
            if take:
                scripts.append(a)
                take = False
            elif a in ("--quiet", "--silent"):
                quiet = True
            elif a.startswith("--expression="):
                scripts.append(a.split("=", 1)[1])
            elif a == "--expression":
                take = True
            elif a.startswith("--"):
                return False  # --in-place, --file and the rest
            elif a.startswith("-") and len(a) > 1:
                flags = a[1:]
                if "e" in flags:
                    flags, rest = flags.split("e", 1)
                    if rest:
                        scripts.append(rest)
                    else:
                        take = True
                if set(flags) - set("nErsuz"):
                    return False  # -i, -f and anything unknown
                quiet = quiet or "n" in flags
            else:
                operands.append(a)
        if not scripts and operands:
            scripts.append(operands[0])
        stripped = re.sub(r"(%s)?" % LOOPBACK + HTTP_STOP_ANY, "", " ".join(scripts))
        return quiet and not take and not re.search(r"[ewW]", stripped)
    return True


def _http_runs_client(command, sites):
    """The rule's structured reading: a localhost stop endpoint (explicit host) in a text in which some parsed
    command names an HTTP client, a computed command, or an interpreter while the text calls an HTTP library; or
    httpie's `:PORT/stop` in an HTTP client's own arguments."""
    names, dynamic = set(), False
    for site, r in sites:
        dynamic = dynamic or r.unresolved == "dynamic_head"
        names.update(os.path.basename(w.value() or w.text).strip("'\"") for w in site.cmd.words)
        names.add(r.name or "")
    if grep(HTTP_STOP_URL, command):
        if dynamic or names & HTTP_CLIENTS:
            return True
        if any(HTTP_INTERPRETERS.match(n) for n in names) and grep(HTTP_LIBRARIES, command):
            return True
    for site, r in sites:
        if r.name in HTTP_CLIENTS or r.unresolved == "dynamic_head":
            if any(re.search(HTTP_STOP_BARE_URL, w.value() if w.value() is not None else w.text) for w in r.args):
                return True
    return False


HTTP_LIFT_PIPE = HTTP_STOP_FILTERS | {"grep", "egrep", "fgrep"}
HTTP_STOP_PATH = re.compile(r"/stop(?![A-Za-z0-9])", re.I)


def _http_path_stops(text):
    """True if a URL in text reaches a stop endpoint once percent-decoded and its dot segments removed, as the
    client (curl normalises `/stops/../stop`) or a server may read it. A word holding whitespace or a control
    character always counts (a client may send `/stops /../stop` as the request path), and so does the path of a
    portless URL word (`localhost/stop`, `http://localhost/stop`)."""
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7f for c in text):
        return True
    portless = re.match(r"(?:[A-Za-z][A-Za-z0-9+.-]*://)?[^/?#]*(/[^?#]*)", text)
    paths = [m.group(1) for m in re.finditer(r":[0-9]+(/[^?#]*)", text)] + ([portless.group(1)] if portless else [])
    for path in paths:
        for _ in range(5):
            dec = urllib.parse.unquote(path)
            if dec == path:
                break
            path = dec
        path = path.replace("\\", "/")
        out = []
        for seg in path.split("/"):
            if seg == "..":
                if len(out) > 1:
                    out.pop()
            elif seg != ".":
                out.append(seg)
        if HTTP_STOP_PATH.search(path) or HTTP_STOP_PATH.search("/".join(out) or "/"):
            return True
    return False


# Per client, the minimal option set shape (b) accepts: (flag-only short letters, flag-only long options,
# value-taking options -> kind of value). Any other option (headers, data, -L/--location, proxies, config files,
# --next, uploads, @file arguments, ...) keeps the refusal. A value option takes its value as the next word (wget's
# `-O` also attached, `-O-` / `-qO-`, and `--output-document=<file>`).
HTTP_LIFT_OPTIONS = {
    "curl": ("sSfiv", {"--silent", "--show-error", "--fail", "--include", "--verbose", "--compressed"},
             {"-o": "file", "--output": "file", "-w": "format", "--write-out": "format", "--max-time": "number",
              "-X": "method", "--request": "method"}),
    "wget": ("q", {"--quiet", "--no-verbose", "-nv"}, {"-O": "file", "--output-document": "file"}),
    "http": ("bhv", {"--body", "--headers", "--verbose", "--check-status", "--ignore-stdin"}, {}),
}
for _alias in ("https", "httpie", "xh", "xhs"):
    HTTP_LIFT_OPTIONS[_alias] = HTTP_LIFT_OPTIONS["http"]
HTTP_LIFT_CLIENTS = frozenset(HTTP_LIFT_OPTIONS)
"""The clients whose request URL is their literal argument, those HTTP_LIFT_OPTIONS reads; a raw socket client (nc,
socat, telnet) is not one."""
HTTP_LIFT_URL = re.compile(r"(?:https?://)?(?:%s):[0-9]{1,5}" % LOOPBACK +
                           r"(?:/[A-Za-z0-9._~/-]*)?(?:\?[A-Za-z0-9._~=&+,-]*)?")
"""The only URL shape (b) lifts: an http(s) URL on a localhost host with a port, a path and an optional query of
plain characters; no userinfo, fragment (`#`), percent-escape, backslash, glob or whitespace."""


def _http_plain_word(w):
    """The static text of a word written as one plain literal (bare, or wholly inside one pair of quotes with no
    escape) holding no control character and no `#`; else None. A bare `?` (a query string's) is kept as written:
    a shell glob cannot put a `/` there, and the URL check reads the result."""
    if not w.parts or not all(p.kind == "lit" or (p.kind == "glob" and set(p.text) <= {"?"}) for p in w.parts):
        return None
    v = "".join(p.text for p in w.parts)
    if w.text not in (v, "'" + v + "'", '"' + v + '"') or (w.text == v and "\\" in v):
        return None
    if "#" in v or any(ord(c) < 0x20 or ord(c) == 0x7f for c in v):
        return None
    return v


def _http_lift_value_ok(kind, v):
    """A value of one of shape (b)'s value options: a plain output file (or `-`), a write-out format that reads no
    file, a number of seconds, or the method GET / HEAD."""
    if kind == "file":
        return v == "-" or _http_out_path_ok(v)
    if kind == "format":
        return bool(v) and not v.startswith("@") and not re.search(r"/stop|\\|%output", v, re.I) \
            and not any(ord(c) < 0x20 or ord(c) == 0x7f for c in v)
    if kind == "number":
        return bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v))
    if kind == "method":
        return v in ("GET", "HEAD")
    return False


def _http_out_path_ok(v):
    """A place shape (b)'s client (or its option) may write to: /dev/null, or a plain literal file path with no
    `..` segment that is not under /dev or /proc (no /dev/tcp, /dev/udp, /dev/fd or /proc/*/fd socket)."""
    if v == locations.NULL_DEVICE:
        return True
    if not re.fullmatch(r"[A-Za-z0-9_./][A-Za-z0-9_./-]*", v):
        return False
    segs = [s for s in v.split("/") if s not in ("", ".")]
    return bool(segs) and ".." not in segs and segs[0] not in ("dev", "proc")


def _http_lift_url_ok(v):
    """A URL word shape (b) lifts: HTTP_LIFT_URL in full, no `.` / `..` path segment, no stop endpoint."""
    if not HTTP_LIFT_URL.fullmatch(v) or _http_path_stops(v):
        return False
    path = re.sub(r"^(?:https?://)?[^/?]*", "", v).split("?", 1)[0]
    return not any(seg in (".", "..") for seg in path.split("/"))


def _http_client_args_ok(name, words):
    """True if a lift client's arguments are only options of its minimal set (HTTP_LIFT_OPTIONS) and exactly one
    URL word that passes _http_lift_url_ok (httpie / xh: optionally preceded by the method GET, and no request
    item: no header, data, query or file item); every word a plain literal free of control characters and `#`."""
    short_flags, long_flags, value_opts = HTTP_LIFT_OPTIONS[name]
    vals = []
    for w in words:
        v = _http_plain_word(w)
        if v is None:
            return False
        vals.append(v)
    i, positional = 0, []
    while i < len(vals):
        a = vals[i]
        i += 1
        if a in long_flags:
            continue
        if a in value_opts:
            if i >= len(vals) or not _http_lift_value_ok(value_opts[a], vals[i]):
                return False
            i += 1
            continue
        if name == "wget" and a.startswith("--output-document="):
            if not _http_lift_value_ok("file", a.split("=", 1)[1]):
                return False
            continue
        if a.startswith("-") and len(a) > 1 and not a.startswith("--"):
            body = a[1:]
            if name == "wget" and "O" in body:
                pre, _o, rest = body.partition("O")
                if set(pre) - set(short_flags):
                    return False
                if rest:
                    if not _http_lift_value_ok("file", rest):
                        return False
                elif i >= len(vals) or not _http_lift_value_ok("file", vals[i]):
                    return False
                else:
                    i += 1
                continue
            if set(body) - set(short_flags):
                return False
            continue
        if a.startswith("-"):
            return False  # any other option, `--` included
        positional.append(a)
    if name not in ("curl", "wget") and len(positional) == 2 and positional[0] == "GET":
        positional = positional[1:]
    return len(positional) == 1 and _http_lift_url_ok(positional[0])


def _http_single_client(command, sites):
    """True if the command is one HTTP client invocation run as written at the top level, alone or piped only into
    pure filters (head, jq, grep, ...; never a shell), whose arguments pass _http_client_args_ok."""
    try:
        from lib.shell_parse import SimpleCommand, parse
        script = parse(command)
    except Exception:  # noqa: BLE001 - the parser unavailable: no lift
        return False
    if script.error is not None or len(script.items) != 1 or not sites:
        return False
    stages = script.items[0][0].stages
    if len(stages) != len(sites) or not all(isinstance(st, SimpleCommand) for st in stages):
        return False
    if any(tuple(site.context) != ("top",) for site, _r in sites):
        return False
    site, r = sites[0]
    name = _http_plain(site, r)
    if name not in HTTP_LIFT_CLIENTS or not _http_client_args_ok(name, list(site.cmd.words[1:])):
        return False
    if any(rd.target is not None and rd.target.value() is None for rd in site.cmd.redirects):
        return False
    if any(rd.op.startswith("<") for rd in site.cmd.redirects):
        return False  # stdin fed to the client can become a request body
    for rd in site.cmd.redirects:
        if rd.close:
            continue
        if rd.dup is not None:
            if rd.dup not in (1, 2):
                return False  # an inherited descriptor may be a socket
        elif rd.writes():
            if rd.target is None or not _http_out_path_ok(rd.target.value()):
                return False  # the client's output (a -w format, a body) must reach no socket
        else:
            return False
    return all(_http_plain(s, rr) in HTTP_LIFT_PIPE and _http_reader_ok(s, rr) for s, rr in sites[1:])


def _http_stop_allowed(command, sites):
    """The whole command has one of the two shapes that send no request to a stop endpoint:
    (a) every parsed command only prints or filters text (grep, rg, echo, cat, sed -n, git log, ... | head), so
        the URL is a mention; or
    (b) the command is a single HTTP client invocation (curl, wget, httpie, xh), alone or piped only into pure
        filters, with no input redirection and output redirected only to /dev/null or a plain file path outside
        /dev and /proc (the pipe filters: /dev/null only), whose options are only those of a minimal set (curl: -s -S -f -i -v,
        --compressed, -o FILE, -w FORMAT (no `/stop`, backslash escape, control character or %output),
        --max-time N, -X GET|HEAD; wget: -q, -nv, -O FILE|-; httpie / xh: -b,
        -h, -v, --check-status, --ignore-stdin, and the method GET only) and whose one URL word is a plain
        literal `[http(s)://]<localhost host>:<port>[/path][?query]` of plain characters (no header, data,
        redirect following, proxy, config or @file option, no `#`, `%`, whitespace or control character, no `.` /
        `..` segment) whose path is no stop endpoint; so `/stops/42` and `/stopwords?lang=en` pass and a request
        that could smuggle or redirect a second request to `/stop` does not."""
    if all(_http_reader_ok(site, r) for site, r in sites):
        return True
    if re.search(HTTP_STOP_ANY + r"(?![A-Za-z0-9])", command):
        return False
    if not _http_single_client(command, sites):
        return False
    found = 0
    for site, r in sites:
        words = list(site.cmd.words) + [a.word for a in site.cmd.assignments] + \
            [rd.target for rd in site.cmd.redirects if rd.target is not None]
        hits = sum(len(re.findall(HTTP_STOP_ANY, w.text)) for w in words)
        if hits:
            if _http_plain(site, r) not in HTTP_CLIENTS:
                return False
            found += hits
    return found == len(re.findall(HTTP_STOP_ANY, command))


def http_stop(command):
    """BS-02: the command may send a request to a localhost port's stop endpoint. It refuses when the raw reading
    does (a client word anywhere and a localhost /stop prefix anywhere) or when a parsed command runs a client
    against a stop endpoint (httpie, xh, [::1], 0.0.0.0, an interpreter's HTTP library), unless the whole command
    has an allow-listed shape (_http_stop_allowed). A parser failure keeps the refusing readings."""
    raw = grep(HTTP_STOP_RAW_CLIENT, command) and grep(HTTP_STOP_RAW_URL, command)
    if not raw and not grep(HTTP_STOP_ANY, command):
        return False
    sites = _http_sites(command)
    if sites is None:
        return raw or (grep(HTTP_STOP_URL, command) and grep(r"(^|[\s;&|(])(https?|xhs?|httpie)\s", command))
    if not (raw or _http_runs_client(command, sites)):
        return False
    return not _http_stop_allowed(command, sites)


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
    if http_stop(command):
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


def _relaxed_writes_namespace(command, ns_re):
    """A write into a namespace: a redirection whose target it is, a listed verb handed it in its own simple command,
    a verb fed it by xargs, or the namespace captured in a variable and then written through one (the whole command
    read as one line, so a heredoc body counts).

    Positional, not semantic. Branch 2 reads each simple command lib/shell_parse.py's walk reaches (with its nested
    payloads, its redirection targets and its heredoc bodies) on its own, so a verb in one command and the namespace
    in another (`touch /tmp/m && cat <ns>`) is no write; `python -m json.tool <ns>` with no second positional only
    prints (with no assignment and no env or other wrapper in front of it). A for/select word list naming the
    namespace is a capture into the loop variable; `$_` (or BASH_REMATCH, BASH_COMMAND, BASH_ARGV) anywhere in a
    command that names it is a write, since it hands the name on to another command. A command the parser cannot
    read is read as one line. Residual over-block: a read is refused when an enumerated verb stands before the
    namespace in its own command for another reason (`cp <ns> /tmp/x`), when an interpreter does the reading, or when
    `$_` follows a read. Residual under-block: a verb not listed, or a path assembled at run time, writes through.
    It raises the cost of a hand-written file; the barrier is hooks/pretool-git-privilege-guard.py, which honours
    only a pipeline-minted grant claimed by the dispatched subagent that holds the matching attestation.
    """
    if not grep(ns_re, command):
        return False
    if grep(r""">>?[&|]?\s*['"]?""" + ns_re, command) or _carries_last_arg(command):
        return True
    sites = _simple_command_texts(command)
    for one in (sites if sites is not None else [command.replace("\n", " ")]):
        if grep(ARTIFACT_WRITE_VERB_RE + ".*" + ns_re, one):
            return True
    one = command.replace("\n", " ")
    listed = any(c.kind in LOOP_VAR_KINDS and any(grep(ns_re, w.text) for w in c.header[1:])
                 for c in _compounds(command) or ())
    return bool(
        (sites is not None and _xargs_fed_writer(command))
        or (listed and grep(ARTIFACT_VAR_WRITE_RE, one))
        or (grep(ARTIFACT_NS_CAPTURE_RE + ns_re, one) and grep(ARTIFACT_VAR_WRITE_RE, one))
        or grep(ARTIFACT_NS_CAPTURE_RE + ns_re + "[^;|&]*" + ARTIFACT_WRITE_VERB_RE, one))


def writes_namespace(command, ns_re):
    """A write into a namespace: a redirection whose target it is, a listed verb handed it, or the namespace captured
    in a variable and then written through one.

    Positional, not semantic. The per-simple-command reading (_relaxed_writes_namespace) decides alone only a
    command of the strict shape _relaxation_shape_ok accepts, where a name cannot flow from one simple command into
    another. Any other command (a function, a loop or other compound that carries the namespace, a capture builtin,
    `$1`, `$_`, `${!v}` ...) also gets the whole-line reading below (the command read as one line, so a heredoc body
    counts; a listed verb anywhere before the namespace is a write, and so is a listed verb or a redirection handed
    any expansion, since set --, printf -v, read, getopts or ${!v} may have put the namespace in it), and a write by
    either is a write, so no refusal of the whole-line reading is lost. Residual over-block: a read is refused when
    an enumerated verb stands before the namespace in its own command for another reason (`cp <ns> /tmp/x`), when an
    interpreter does the reading, and for a command outside the strict shape when a verb stands anywhere before the
    namespace, a verb is handed any expansion, or a compound only reads it
    (`for f in <ns>*; do python3 -m json.tool "$f"; done`). Residual under-block: a verb not listed, or a path
    assembled at run time, writes through. It raises the cost of a hand-written file; the barrier is
    hooks/pretool-git-privilege-guard.py, which honours only a pipeline-minted grant claimed by the dispatched
    subagent that holds the matching attestation.
    """
    if not grep(ns_re, command):
        return False
    if _arg_write_named(command, lambda text: grep(ns_re, text)):
        return True
    if _relaxation_shape_ok(command, lambda text: grep(ns_re, text)):
        return _relaxed_writes_namespace(command, ns_re)
    one = command.replace("\n", " ")
    return bool(
        grep(r""">>?[&|]?\s*['"]?""" + ns_re, command)
        or grep(ARTIFACT_WRITE_VERB_RE + ".*" + ns_re, one)
        or (grep(ARTIFACT_NS_CAPTURE_RE + ns_re, one) and grep(ARTIFACT_VAR_WRITE_RE, one))
        or grep(ARTIFACT_NS_CAPTURE_RE + ns_re + "[^;|&]*" + ARTIFACT_WRITE_VERB_RE, one)
        or grep(r""">>?[&|]?\s*['"]?\$|""" + ARTIFACT_WRITE_VERB_RE + r".*\$", one)
        or _relaxed_writes_namespace(command, ns_re))


_SHAPE_CAPTURE_BUILTINS = frozenset({"set", "read", "mapfile", "readarray", "getopts", "declare", "typeset", "local",
                                     "export", "readonly", "let", "trap", "alias", "eval", "source", ".", "unset",
                                     "shopt", "enable", "builtin", "hash", "coproc", "exec", "caller", "fc",
                                     "history", "compgen", "complete", "bind", "unalias", "wait", "printf"})
"""Builtins that store a word in a variable, positional parameter, alias, trap or function, or run text as code;
printf only with -v (checked below)."""
_SHAPE_PARAM_RE = re.compile(r"[#!]?([0-9@*!?$#-]|_(?![A-Za-z0-9_])|BASH|FUNCNAME|PIPESTATUS|OPTARG|OPTIND"
                             r"|REPLY|MAPFILE|COMP_|READLINE_)|!.*|[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?@.*")
"""Positional, special, indirect (`${!v}`) and transforming (`${v@P}`) expansions, and the variables builtins fill:
each carries text from somewhere other than the word itself."""
_SHAPE_HISTORY_RE = re.compile(r"!([$*^:!#]|-?[0-9])")
"""A history expansion (`!$`, `!!`, `!-1`) outside single quotes: inert in a non-interactive shell, still read as a
carried word."""


def _unquoted_single(text):
    """The text with its single-quoted and $'..' spans blanked (they are inert); double quotes are kept."""
    out, i, n, dq = [], 0, len(text), False
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if c == '"':
            dq = not dq
        elif c == "'" and not dq:
            j = text.find("'", i + 1)
            if j < 0:
                return text
            out.append("''")
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _shape_params(command):
    """The text of every active parameter expansion (`1`, `1%/`, `!v`, `_` ...) in every simple command the walk
    reaches, its heredoc bodies and every compound's header and redirections, nested ones included; None when the
    text does not parse."""
    try:
        from lib.shell_parse import active_parts
        sites = _parsed_sites(command)
        compounds = _shape_compounds(command)
        if sites is None or compounds is None:
            return None
        parts = []
        for site, _res in sites:
            for w in _site_words(site.cmd):
                parts.extend(active_parts(w.parts))
            for r in site.cmd.redirects:
                if r.hd is not None:
                    parts.extend(active_parts(r.hd.expansions))
        for k, _piped in compounds:
            for w in list(k.header) + [r.target for r in k.redirects if r.target is not None]:
                parts.extend(active_parts(w.parts))
        out, seen = [], set()
        while parts:
            part = parts.pop()
            if id(part) in seen:
                continue
            seen.add(id(part))
            if part.kind == "param":
                out.append(part.text)
            parts.extend(part.inner())
        return out
    except Exception:  # noqa: BLE001
        return None


_GIT_PROGRAM_ENV_RE = re.compile(r"(^|[^A-Za-z0-9_])(GIT_EXTERNAL_DIFF|GIT_PAGER|PAGER|GIT_EDITOR|EDITOR|VISUAL"
                                 r"|GIT_SEQUENCE_EDITOR|GIT_SSH|GIT_SSH_COMMAND|GIT_ASKPASS|SSH_ASKPASS|GIT_EXEC_PATH"
                                 r"|GIT_[A-Za-z0-9_]*|HOME|XDG_CONFIG_HOME|LESSOPEN|LESSCLOSE|BASH_ENV|ENV)([^A-Za-z0-9_]|$)")
"""Environment variables that make git (or a shell it starts) run a program of their choosing, or read a config
(HOME, XDG_CONFIG_HOME, any GIT_*: GIT_DIR, GIT_COMMON_DIR, GIT_WORK_TREE, GIT_CONFIG_* ...) that names one."""


def _shape_compounds(command):
    """(compound, piped) for every compound command in the text (payloads, substitutions and compound bodies too),
    piped when it is a stage of a pipeline of more than one; None when the text does not parse."""
    try:
        from lib.shell_parse import parse, active_parts, Compound, _nested_scripts
        top = parse(command)
        if top.error is not None:
            return None
        stack, seen, out = [top] + list(_nested_scripts(top)), set(), []
        while stack:
            script = stack.pop()
            if id(script) in seen or not hasattr(script, "items"):
                continue
            seen.add(id(script))
            for pl, _sep in script.items:
                for stage in pl.stages:
                    if not isinstance(stage, Compound):
                        continue
                    out.append((stage, len(pl.stages) > 1))
                    stack.extend(b for b in stage.body if hasattr(b, "items"))
                    for w in list(stage.header) + [r.target for r in stage.redirects if r.target is not None]:
                        stack.extend(p.body for p in active_parts(w.parts) if p.body is not None)
        return out
    except Exception:  # noqa: BLE001
        return None


def _relaxation_shape_ok(command, carries):
    """True when no protected name can flow from one simple command into another, so each may be read on its own.

    `carries(text)` says whether a text names what the calling rule protects. The whole command parses and holds:
    no function definition; no compound command (a loop, if, case, group, subshell or coproc feeds its body from a
    word list, a redirection or a here-string) unless it is [[ ]] or (( )), or it carries no protected name (in its
    text, with quotes and backslashes taken out), has no redirection of its own, is no pipeline stage and no heredoc
    is in the command; no builtin that stores a word or runs text (set, read, mapfile, readarray, getopts, declare,
    typeset, local, export, readonly, let, trap, alias, eval, source, printf -v ...); no computed or unreadable
    command word; no positional, special, indirect or transforming expansion ($1, $@, $_, ${!v}, ${v@P}, BASH_*);
    beside a git, no variable that makes git run a program or read another config; and the word conditions of
    _shape_strict_ok (bare command words, no assignment or env wrapper, no directory change, no `&`, no write
    target, no here-string carrying a name, nothing that runs a file beside the writer script's name). Fail closed:
    anything not read is not ok.
    """
    if _SHAPE_HISTORY_RE.search(_unquoted_single(command)):
        return False
    params = _shape_params(command)
    if params is None or any(_SHAPE_PARAM_RE.match(t) or "BASH_" in t for t in params):
        return False
    compounds = _shape_compounds(command)
    if compounds is None:
        return False
    for k, piped in compounds:
        if k.kind in ("cond", "arith"):
            continue
        text = command[k.span[0]:k.span[1]]
        if k.kind in DEFINER_KINDS or not text or piped or k.redirects or "<<" in command \
                or "$'" in text or carries(text) or carries(re.sub(r"""[\\'"]""", "", text)):
            return False
    sites = _parsed_sites(command)
    if sites is None:
        return False
    for site, res in sites:
        if site.dynamic or site.templated or res.unresolved is not None or (res.name is None and site.cmd.words):
            return False
        if _shape_word_computed(site.cmd):
            return False
        heads = {res.name} | {n for n, _o in res.wrappers}
        if site.cmd.words and site.cmd.words[0].value() is not None:
            heads.add(site.cmd.words[0].value().rsplit("/", 1)[-1])
        if heads & (_SHAPE_CAPTURE_BUILTINS - {"printf"}):
            return False
        if res.name == "git" and any(w.value() in ("config", "alias") for w in res.args):
            return False
        if "printf" in heads and any((w.value() or "-v").startswith("-") and "v" in (w.value() or "-v")
                                     for w in site.cmd.words[1:]):
            return False
    if re.search(r"(^|[^A-Za-z0-9_])git([^A-Za-z0-9_]|$)", command) and _GIT_PROGRAM_ENV_RE.search(command):
        return False
    try:
        return _shape_strict_ok(command, carries, sites)
    except Exception:  # noqa: BLE001
        return False


_SHAPE_COMPUTED_PARTS = frozenset({"brace", "cmdsub", "backtick", "procsub_in", "procsub_out"})


def _shape_word_computed(cmd):
    """True when a word of the simple command (assignment, command, argument or redirection target) holds a brace
    expansion or a command or process substitution: its words are not the ones written, so the strict shape does
    not take it."""
    from lib.shell_parse import active_parts
    return any(p.kind in _SHAPE_COMPUTED_PARTS for w in _site_words(cmd) for p in active_parts(w.parts))


_SHAPE_ENV_OK_RE = re.compile(r"LC_[A-Z]+|LANG|TZ|NO_COLOR|TERM")
"""The only assignments the strict shape takes: each changes how a command prints, never what it runs or reads."""
_SHAPE_ENV_SENSITIVE_RE = re.compile(
    r"PATH|HOME|IFS|ENV|BASH_ENV|CDPATH|SHELLOPTS|BASHOPTS|PS4|PROMPT_COMMAND|TMPDIR|PAGER|EDITOR|VISUAL|MANPAGER"
    r"|SHELL|POSIXLY_CORRECT|PWD|OLDPWD|TMP|TEMP|CC|CXX|CPP|AR|AS|FC|PS[0-9]"
    r"|(LD|PYTHON|PERL|RUBY|NODE|GIT|XDG|RIPGREP|GREP|LESS|JQ|SSH|GNUPG|GPG)[A-Z0-9_]*"
    r"|.*(PATH|DIR|HOME|CONFIG|OPTS|OPTIONS|PROXY|_proxy)[A-Za-z0-9_]*", re.IGNORECASE)
"""Names a program or the shell reads (case ignored): no standalone assignment to one stays in the strict shape."""
_SHAPE_STANDALONE_RE = re.compile(r"[a-z_][a-z0-9_]*|[A-Z][A-Z0-9_]{0,2}")
"""The standalone assignments (`x=v; cmd`) the strict shape takes besides _SHAPE_ENV_OK_RE: a lower-case shell
variable, or an upper-case name of one to three characters (`NS`, `T`, `OUT`), that matches no
_SHAPE_ENV_SENSITIVE_RE pattern (`http_proxy`, `dir`, `shell`, `IFS`, `PWD`, `TMP`, `CC` are refused). Any longer
upper-case or mixed name (`SHELL`, `GLOBIGNORE`, `FOO_BAR`) takes the command out of the shape."""
_SHAPE_WRAPPERS = frozenset({"nice", "nohup", "timeout", "command", "xargs", "sudo", "setsid", "env"})
"""Wrappers that run their command as named (env only with no option, sudo only with _SHAPE_SUDO_OPTS)."""
_SHAPE_SUDO_OPTS = frozenset({"-u", "--user", "-g", "--group", "-E", "--preserve-env", "-n", "--non-interactive",
                              "-H", "--set-home"})
"""sudo's options that keep its command as named: -s/--shell and -i/--login run it through `$SHELL -c`, and any
other option (-D, -R, -A, -C, -T ...) changes where or how it runs."""
# The global options that point git at another directory, file, ref namespace or program set (every value option
# but -c, and --exec-path).
_GIT_DIR_OPTS = (GIT_GLOBAL_VALUE_OPTS | {"--exec-path"}) - {"-c"}
_SHAPE_RUNS_FILE = re.compile(r"((ba|z|da|k|c|tc|fi|r)?sh|busybox|i?python[0-9.]*|pypy[0-9.]*|node(js)?[0-9.]*|deno|bun"
                              r"|perl[0-9.]*|ruby[0-9.]*|php[0-9.]*|lua[0-9.]*|tclsh|wish|expect|make|[gmn]?awk|sed"
                              r"|gsed|exec|source|\.|eval|xargs|parallel|watch|script|su|builtin|strace|ltrace)")
"""Commands that run a file or text they are handed: beside a mention of the writer script, the shape refuses them."""


def _shape_scripts(command):
    """Every script in the text: the top one, payloads, substitutions and compound bodies; None when unparsed."""
    try:
        from lib.shell_parse import parse, active_parts, Compound, _nested_scripts
        top = parse(command)
        if top.error is not None:
            return None
        stack, seen, out = [top] + list(_nested_scripts(top)), set(), []
        while stack:
            script = stack.pop()
            if id(script) in seen or not hasattr(script, "items"):
                continue
            seen.add(id(script))
            out.append(script)
            stack.extend(_nested_scripts(script))
            for pl, _sep in script.items:
                for stage in pl.stages:
                    if isinstance(stage, Compound):
                        stack.extend(b for b in stage.body if hasattr(b, "items"))
                        for w in list(stage.header) + [r.target for r in stage.redirects if r.target is not None]:
                            stack.extend(p.body for p in active_parts(w.parts) if p.body is not None)
        return out
    except Exception:  # noqa: BLE001
        return None


def _arg_write_targets(res):
    """The files a reader or filter writes through an argument: sort -o/--output (clustered or abbreviated), uniq's
    second operand, tee's operands, git --output (any abbreviation) or -o. Unknown means a target."""
    name, vals = res.name, [w.value() for w in res.args]
    if any(v is None for v in vals):
        return ["?"] if name in ("sort", "uniq", "tee") else []
    out = []
    if name == "tee":
        out += [v for v in vals if not v.startswith("-")]
    elif name == "sort":
        k = 0
        while k < len(vals):
            v = vals[k]
            if v == "--":
                break
            if v.startswith("--") and len(v) > 2:
                key = v.split("=", 1)[0]
                if "--output".startswith(key) and len(key) >= 3:
                    out.append(v.split("=", 1)[1] if "=" in v else (vals[k + 1] if k + 1 < len(vals) else "?"))
            elif v.startswith("-") and len(v) > 1 and "o" in v[1:]:
                i = v.index("o", 1)
                if not any(c in "kt" for c in v[1:i]):
                    out.append(v[i + 1:] or (vals[k + 1] if k + 1 < len(vals) else "?"))
            k += 1
    elif name == "uniq":
        ops, skip = [], False
        for v in vals:
            if skip:
                skip = False
            elif v in ("-f", "-s", "-w", "--skip-fields", "--skip-chars", "--check-chars"):
                skip = True
            elif v == "-" or not v.startswith("-"):
                ops.append(v)
        out += ops[1:]
    elif name == "git":
        for v in vals:
            key = v.split("=", 1)[0]
            if (key.startswith("--o") and "--output".startswith(key)) or key == "-o":
                out.append("?")
    return out


def _arg_write_named(command, carries):
    """A tee, sort -o, uniq second operand or git --output whose target names what the caller protects (or cannot
    be read), whatever the shape: `sort -o "<sentinel with a space>"` and `uniq - <grant>` write it."""
    for _site, res in _parsed_sites(command) or ():
        if any(t == "?" or carries(t) for t in _arg_write_targets(res)) and carries(command):
            return True
    return False


def _shape_strict_ok(command, carries, sites):
    """The strict shape's conditions on the words themselves (see _relaxation_shape_ok).

    Every command word is a bare name or /bin/<name> or /usr/bin/<name> (`./cat`, `/tmp/x/python3` run a file of the
    caller's choosing); no prefix assignment (or one handed to env) but LC_*, LANG, TZ, NO_COLOR, TERM, no
    standalone one but those and a lower-case name matching no _SHAPE_ENV_SENSITIVE_RE pattern (_SHAPE_STANDALONE_RE),
    and no array, subscripted or `+=` assignment; no wrapper but nice, nohup, timeout, command, xargs, setsid, an
    option-less env and a sudo whose options are among -u, -g, -E, -n, -H (not -s/-i); no cd, pushd, popd and no
    git -C, --git-dir, --work-tree or other directory option; no background `&`; no heredoc or here-string whose body
    names a protected name; no write target but /dev/null (a redirection, tee, sort -o, uniq's second operand, git
    --output); a `git -c` only with an exact display key (_git_config_inert); and, when a word names the writer script,
    no write target at all and no command that runs a file (an interpreter, a shell, sed, awk, make, find ...)."""
    scripts = _shape_scripts(command)
    if scripts is None or any(sep == "&" for sc in scripts for _pl, sep in sc.items):
        return False
    writer = any(n in command for n in BULK_NAMES[1:])
    for site, res in sites:
        c = site.cmd
        heads = list(c.words[:1]) + ([res.head] if res.head is not None else [])
        if any(w.value() is None or not _SHAPE_HEAD_RE.fullmatch(w.value()) for w in heads):
            return False
        for a in tuple(c.assignments) + tuple(res.assignments):
            if _SHAPE_ENV_OK_RE.fullmatch(a.name or ""):
                continue
            if c.words or not _SHAPE_STANDALONE_RE.fullmatch(a.name or "") or \
                    _SHAPE_ENV_SENSITIVE_RE.fullmatch(a.name) or \
                    not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=(?!\().*", a.word.text or "", re.S):
                return False
        for name, opts in res.wrappers:
            if name not in _SHAPE_WRAPPERS or (name == "env" and opts) or \
                    (name == "sudo" and any(o not in _SHAPE_SUDO_OPTS for o, _v in opts)):
                return False
        if res.name in CWD_BUILTINS:
            return False
        if res.name == "git":
            for w in res.args:
                v = w.value() or ""
                if v in _GIT_DIR_OPTS or v.split("=", 1)[0] in _GIT_DIR_OPTS:
                    return False
                if not v.startswith("-"):
                    break
        for r in c.redirects:
            body = r.hd.body if r.hd is not None else (r.target.text if r.op == "<<<" and r.target is not None else None)
            if body is not None and (carries(body) or carries(re.sub(r"""[\\'"]""", "", body)) or "$'" in body):
                return False
            if r.target is not None and r.writes() and r.target.value() != locations.NULL_DEVICE:
                return False
        if any(t != locations.NULL_DEVICE for t in _arg_write_targets(res)):
            return False
        if writer:
            names = {res.name} | {n for n, _o in res.wrappers}
            if any(n is not None and _SHAPE_RUNS_FILE.fullmatch(n) for n in names) or \
                    any("/" in (w.value() or "/") for w in heads) or \
                    (res.name == "find" and any(w.value() in _BULK_FIND_ACTIONS for w in res.args)) or \
                    (res.name in _BULK_FILTERS and not _bulk_static_args(res.name, res.args)):
                return False
    if writer:
        try:
            from lib.shell_parse import parse, write_targets
            if any(t.path != locations.NULL_DEVICE for t in write_targets(parse(command))):
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


def _site_words(cmd):
    """A simple command's assignment, command and redirection-target words."""
    return [a.word for a in cmd.assignments] + list(cmd.words) + [r.target for r in cmd.redirects
                                                                 if r.target is not None]


def _parsed_sites(command):
    """(site, resolved) for every simple command lib/shell_parse.py's walk reaches; None when it cannot read the text."""
    try:
        from lib.shell_parse import parse, walk, resolve
        script = parse(command)
        if script.error is not None:
            return None
        return [(site, resolve(site.cmd)) for site in walk(script)]
    except Exception:  # noqa: BLE001
        return None


_LAST_ARG_RE = re.compile(r"\$(\{[#!]?)?_(?![A-Za-z0-9_])|BASH_REMATCH|BASH_COMMAND|BASH_ARGV")
"""`$_` (the last argument of the command before) and the shell variables that hold another command's text."""


def _carries_last_arg(command):
    """A use of `$_` or of a variable holding another command's text, quoted or not (fail closed)."""
    return bool(_LAST_ARG_RE.search(command))


def _compounds(command):
    """Every compound command in the text (in payloads, substitutions and compound headers too); None when unparsed."""
    try:
        from lib.shell_parse import parse, active_parts, Compound, _nested_scripts
        top = parse(command)
        if top.error is not None:
            return None
        stack, seen, out = [top] + list(_nested_scripts(top)), set(), []
        while stack:
            script = stack.pop()
            if id(script) in seen or not hasattr(script, "items"):
                continue
            seen.add(id(script))
            for pl, _sep in script.items:
                for stage in pl.stages:
                    if not isinstance(stage, Compound):
                        continue
                    out.append(stage)
                    stack.extend(b for b in stage.body if hasattr(b, "items"))
                    for w in list(stage.header) + [r.target for r in stage.redirects if r.target is not None]:
                        stack.extend(p.body for p in active_parts(w.parts) if p.body is not None)
        return out
    except Exception:  # noqa: BLE001
        return None


_JSON_TOOL_FLAGS = ("--sort-keys", "--no-ensure-ascii", "--json-lines", "--tab", "--no-indent", "--compact")


def _json_tool_prints_only(res):
    """`python -m json.tool [options] infile`: one positional and no outfile, so it only prints what it reads.

    Only as written: an assignment (PYTHONPATH, PYTHONSTARTUP ...) or a wrapper in front of it can change what runs."""
    if not re.fullmatch(r"python[0-9.]*", res.name or "") or res.payload is not None:
        return False
    if res.assignments or res.wrappers or res.unresolved is not None:
        return False
    vals = res.argv()
    if any(v is None for v in vals) or "-m" not in vals:
        return False
    k = vals.index("-m")
    if vals[k + 1:k + 2] != ["json.tool"] or not all(re.fullmatch(r"-[BEIsSuqR]+", v) for v in vals[:k]):
        return False
    positional, rest = 0, vals[k + 2:]
    while rest:
        v, rest = rest[0], rest[1:]
        if v == "--indent" and rest:
            rest = rest[1:]
        elif v in _JSON_TOOL_FLAGS or v.startswith("--indent="):
            continue
        elif v.startswith("-"):
            return False
        else:
            positional += 1
    return positional == 1


def _simple_command_texts(command):
    """Each simple command's own text (words, redirection targets, heredoc bodies) on one line, None when unparsed.

    A `python -m json.tool <file>` that only prints is left out: it is handed the file to read."""
    sites = _parsed_sites(command)
    if sites is None:
        return None
    out = []
    for site, res in sites:
        if _json_tool_prints_only(res):
            continue
        text = " ".join([w.text for w in _site_words(site.cmd)]
                        + [r.hd.body for r in site.cmd.redirects if r.hd is not None])
        out.append(text.replace("\n", " "))
    return out


def _xargs_fed_writer(command):
    """A listed write verb run by xargs: its operands come from its input, so whatever that names may be written."""
    for _site, res in _parsed_sites(command) or ():
        if res.head is not None and any(name == "xargs" for name, _opts in res.wrappers):
            if grep(ARTIFACT_WRITE_VERB_RE, " ".join(w.text for w in (res.head,) + tuple(res.args))):
                return True
    return False


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
from lib.shell_parse import INTO_DIR_VERBS  # noqa: E402 -- the copy, move and link verbs
from lib.shell_parse import (  # noqa: E402  (the shell facts these rules read)
    BOTH_STREAMS_OPS, CD_TARGET_BUILTINS, COMMON_SHELLS, CWD_BUILTINS,
    DUP_OPS, FIND_NAME_TESTS, GIT_MESSAGE_OPTS, GREP_NAMES, HEREDOC_OPS, PYTHON_NAMES, SED_QUIET_OPTS, SED_SCRIPT_OPTS,
    SORT_OUTPUT_OPTS, STATIC_PART_KINDS,
    DECLARATION_BUILTINS, DEFINER_KINDS, GIT_RESTORE_SOURCE_OPTS, LOOP_VAR_KINDS, OPTION_ENDS, OPTION_SIGNS,
    OUTPUT_REDIRECT_OPS, PIPE_OPS, PRINTERS, REDIRECT_OPS)
from lib import locations  # noqa: E402

_SHAPE_HEAD_RE = re.compile("[^/]+|(?:%s)/[^/]+" % "|".join(locations.BIN_DIRS))
"""The strict shape's command word (_shape_strict_ok): a bare name found on PATH, or <a plain program directory>/<name>."""

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
_CONSENT_COPIERS = frozenset(INTO_DIR_VERBS + ("link",))  # link(1): read failing closed
# Tools that extract or check out files whose names they read from a file (an archive, a package, a stored gzip
# name) into a directory: program -> how _consent_unpack_dirs reads its options (rule 3b). git checkout-index
# --prefix and git init/clone are read by _consent_git_tree.
_CONSENT_UNPACKERS = {
    "tar": "tar", "bsdtar": "tar", "gtar": "tar", "unzip": "unzip", "cpio": "cpio", "bsdcpio": "cpio",
    "7z": "7z", "7za": "7z", "7zr": "7z", "gzip": "gzip", "gunzip": "gzip", "zcat": "gzip", "pigz": "gzip",
    "unpigz": "gzip", "ar": "ar", "dpkg-deb": "deb", "dpkg": "deb", "pax": "pax", "unrar": "rar", "rar": "rar",
    "unar": "unar", "lha": "lha", "lhasa": "lha"}
_CONSENT_DEVICES = locations.TERMINAL_SINKS
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


# The consent view's lattice: a token's origin is lit, glob, state (the state directory itself) or unk (a value
# not known here); a variable's kind is static, word, text, state or any.
_CONSENT_UNKNOWN = ("unk", "state")  # an origin that is no known literal
_CONSENT_STATEFUL = ("state", "any")  # a variable kind that depends on what ran before


class _ConsentView:
    """What one command can do to the consent flag in `state`: variables, working directories and path words read
    as glob tokens tagged by origin (lit, glob, state: the state directory itself, unk: a value not known here)."""

    def __init__(self, sp, script, sites, command, cwd, state):
        self.sp, self.state = sp, state
        self.state_is_tmp = _consent_same_dir(state, locations.DEFAULT_TEMP_DIR)
        self.home = os.environ.get("HOME", "")
        self.command = command
        self.defs = {}  # variable -> list of ("static", text) | ("word", Word) | ("text", source text) | ("state",)
        self._memo, self._busy = {}, set()
        for s in sites:
            cmd = s.cmd
            for a in cmd.assignments:
                self._define(a.name, a)
            r = sp.resolve(cmd)
            if r.name in sp.DECLARATION_BUILTINS:
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
                if c.kind in sp.LOOP_VAR_KINDS and c.header and c.header[0].value():
                    name = c.header[0].value()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        for w in c.header[1:] or [None]:
                            self.defs.setdefault(name, []).append(("word", w) if w is not None else ("text", "$@"))
        # The working directories a relative path is read from: (path or None when computed, explicit?) - the call's
        # cwd, then each cd / pushd target in the command (explicit: the command itself names it).
        self.cwds = [(cwd, False)]
        for s in sites:
            r = sp.resolve(s.cmd)
            if r.name not in sp.CD_TARGET_BUILTINS:
                continue
            args = [w for w in r.args if (w.value() or "") not in sp.CD_OPTIONS]
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

    def made(self, p):
        """The path `$(mktemp [-d] TEMPLATE)` prints, written as its template: mktemp makes that name new, below the
        template's directory, so it is never the state directory itself. None for any other substitution."""
        cmds = [s.cmd for s in self.sp.walk(p.body)] if p.body is not None and p.body.error is None else []
        vals = [w.value() for w in cmds[0].words] if len(cmds) == 1 and not (cmds[0].redirects or cmds[0].assignments) else []
        ops = [v for v in vals[1:] if v not in ("-d", "-q", "--directory", "--quiet")]
        return ops[0] if vals[:1] == ["mktemp"] and None not in vals and len(ops) == 1 and ops[0][:1] not in ("-", "") else None

    def marks_state(self, text):
        """Does computed source text (a substitution's body, a read's input) point at the state directory?"""
        text = text or ""
        if self.state in text or os.path.realpath(self.state) in text or "CLAUDE_STATE_DIR" in text:
            return True
        if self.state_is_tmp and re.search(locations.DEFAULT_TEMP_DIR + r"\b|\bTE?MP(DIR)?\b|\bmktemp\b", text):
            return True
        if self.cwd_state(".") and re.search(r"\bpwd\b|\bO?L?D?PWD\b|\$\{?PWD|\bdirs\b", text):
            return True
        for name in re.findall(r"\$\{?!?([A-Za-z_][A-Za-z0-9_]*)", text):
            if self.var(name)[0] in _CONSENT_STATEFUL:
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
            elif p.kind in ("cmdsub", "backtick") and self.made(p):
                out.extend((("c", ch), "lit") for ch in self.made(p))
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
        if named and any(o in _CONSENT_UNKNOWN for _, o in toks):
            return "its target is computed in a command that names the consent flag"
        if not base or not _consent_name_may_match([t for t, _ in base]):
            return None
        where = self.dir_state(dtoks)
        if where is None:
            return None
        if any(o in _CONSENT_UNKNOWN and t[0] != "c" for t, o in base):
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
        if any(o in _CONSENT_UNKNOWN and t[0] != "c" for t, o in base):
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
}


def _consent_spec(name):
    if name in ("cp", "mv", "ln", "install"):  # the copy verbs' getopt tables are the parser's
        from lib import shell_parse as sp
        return sp.VERBS[name][0]
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
        from lib.shell_parse import NO_TARGET_DIR_OPTS, TARGET_DIR_OPTS
        no_dir = bool(names.intersection(NO_TARGET_DIR_OPTS)) or (
            r.name == "ln" and bool(names & {"-n", "--no-dereference"}))
        recursive = bool(names & {"-r", "-R", "-a", "--recursive", "--archive"})
        targets = [v for o, v, _ in opts if o in TARGET_DIR_OPTS]
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


_EXTRACT_LETTERS = ("x", "e")  # the one-letter commands of rar, unrar, 7z and lha that extract


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
                extracts = len(lead) < len(toks) or (k[:1] in _EXTRACT_LETTERS if name == "rar" else bool(
                    set(k.split("w=")[0]) & set(_EXTRACT_LETTERS)))
                if name == "lha" and "w=" in lead:
                    dests.append(toks[lead.index("w=") + 2:])
                    outdir = True
            elif not lead.startswith("-"):
                dests.append(toks)
            i += 1 + skip
        return extracts, dests + ([] if outdir else [here])
    extracts = bool(lex) and lex[0][1] in _EXTRACT_LETTERS
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
                if any(o in _CONSENT_UNKNOWN for _, o in val):
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
        if info[0] in _CONSENT_STATEFUL:
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
            elif v is None and any(p.kind not in STATIC_PART_KINDS for p in w.parts) and "worktree" in w.text.lower():
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
        if d and (d[0][0] == ("c", "/") or d[0][1] in _CONSENT_UNKNOWN or any(o == "state" for _, o in d)):
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
            if info[0] in _CONSENT_STATEFUL:
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
    if base in GIT_DIR_CONFIG_FILES:
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
        if view.var(name)[0] in _CONSENT_STATEFUL:
            return True
    return False


def _consent_read_only(cmd, name, view, named_writes):
    """None when the simple command is one of the read-only shapes, else why not."""
    from lib.shell_parse import AWK_DATA_OPTS, AWK_NAMES
    words = list(cmd.words[1:])
    vals = [w.value() for w in words]
    if name in _CONSENT_STRICT_ARGS and any(v is None and any(p.kind not in STATIC_PART_KINDS for p in w.parts)
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
        scripts = [_consent_text(v) for o, v, _ in opts if o in SED_SCRIPT_OPTS]
        if not scripts:
            scripts = [_consent_text(view.tokens(w)) for w in operands[:1]]
        for s in scripts:
            s = re.sub(r"\\.", "", s or "")
            s = re.sub(r"/[^/\n]*/", "", s)
            if re.search(r"[wWe]", s):
                return "a `sed` script can write a file or run a command"
        return None
    if name in AWK_NAMES:
        prog, skip = None, False
        for i, v in enumerate(vals):
            if skip:
                skip = False
                continue
            if v in AWK_DATA_OPTS:
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
            if o in SORT_OUTPUT_OPTS and v is not None:
                named_writes.append(w if w is not None else ("toks", v))
        return None
    if name == "tee":
        for w, v in zip(words, vals):
            if not (v or "").startswith("-") or v == "-":
                named_writes.append(w)
        return None
    if name == "git":
        gopts, i = git_global_options(vals)
        i = len(vals) if i is None else i
        for o, _v in gopts:
            if vals[o] != "-C" and vals[o] not in GIT_INERT_FLAGS:
                return f"`git {vals[o]}` is not a read-only git option"
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
                if v in GIT_MESSAGE_OPTS:
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
        if t.path is not None and (t.path in _CONSENT_DEVICES or t.path.startswith(locations.FD_DIR)):
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
        if "xargs" in [n for n, _ in r.wrappers] or sp.basename(head) in sp.ITEM_RUNNERS or \
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
        if name in PRINTERS and any(CONSENT_TOKEN in _consent_norm(w.text) for w in cmd.words[1:]):
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


_BULK_READERS = frozenset({"ls", "stat", "cat", "file", "wc", "head", "tail", "grep", "egrep", "fgrep", "rg", "jq",
                           "find", "test", "[", "git"})
"""The commands that may name the bulk sentinel or its writers: each only reads what it is handed."""
_BULK_FILTERS = _BULK_READERS | {"sort", "uniq", "cut", "nl", "less", "more", "column", "tr"}
"""What may read a pipe or xargs input that carries one of the names."""
_BULK_CODE_ARG = frozenset({"sed", "gsed", "awk", "gawk", "mawk", "nawk", "eval", "source", ".", "trap", "su", "ssh",
                            "watch", "parallel", "flock", "script", "tmux", "screen", "expect", "make"})
"""Commands whose arguments are code: a name anywhere in them is run, not read (sed's `w` writes a file)."""
_BULK_INTERPRETER = re.compile(r"((ba|z|da|k|c|tc|fi|r)?sh|i?python[0-9.]*|node(js)?[0-9.]*|perl[0-9.]*|ruby[0-9.]*"
                               r"|php[0-9.]*|lua[0-9.]*)")
_BULK_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
                                "-fls"})
_GIT_PLAIN = frozenset({"diff", "log", "show", "grep", "status", "add", "commit", "rm", "mv", "restore", "checkout",
                        "switch", "reset", "blame", "annotate", "ls-files", "ls-tree", "cat-file", "rev-parse",
                        "rev-list", "shortlog", "whatchanged", "describe", "check-ignore", "check-attr", "diff-tree",
                        "diff-files", "diff-index", "range-diff", "reflog", "branch", "tag", "merge-base", "name-rev",
                        "show-ref", "for-each-ref", "stash", "merge", "cherry-pick", "revert", "version"})
"""git subcommands that take a protected name as a path or message to read, never as code or an output file."""
_GIT_RUN_OR_WRITE_OPTS = git_facts.GIT_RUN_OR_WRITE_OPTIONS
_BULK_BENIGN = frozenset({"echo", "printf", "cd", "pwd", "true", "false", ":"})
"""Commands that neither run nor write what they are handed (beside a redirection, read on its own)."""
_BULK_DECLARE = frozenset({"export", "declare", "local", "readonly", "typeset", "alias", "let"})
"""Builtins whose arguments are assignments: a name in one is carried in a variable to a later command."""
_BULK_FILTER_OPTS = {
    # name: (short flags, short options taking a value, exact long flags, exact long options taking a value, digits)
    "sort": ("bdfgiMhnRrVsuzcCm", "ktSTo", {"--ignore-leading-blanks", "--dictionary-order", "--ignore-case",
             "--general-numeric-sort", "--ignore-nonprinting", "--month-sort", "--human-numeric-sort",
             "--numeric-sort", "--random-sort", "--reverse", "--version-sort", "--stable", "--unique",
             "--zero-terminated", "--merge", "--check", "--debug"},
             {"--key", "--field-separator", "--buffer-size", "--temporary-directory", "--output", "--parallel"}, False),
    "uniq": ("cdDiuz", "fsw", {"--count", "--repeated", "--ignore-case", "--unique", "--zero-terminated"},
             {"--skip-fields", "--skip-chars", "--check-chars"}, True),
    "head": ("qvz", "cn", {"--quiet", "--silent", "--verbose", "--zero-terminated"}, {"--bytes", "--lines"}, True),
    "tail": ("qvzfF", "cns", {"--quiet", "--silent", "--verbose", "--zero-terminated", "--follow", "--retry"},
             {"--bytes", "--lines", "--sleep-interval"}, True),
    "wc": ("lwcmL", "", {"--lines", "--words", "--bytes", "--chars", "--max-line-length"}, set(), False),
    "less": ("RrSNnFXEeiIMmsqQcfKwWJaBGL~", "xyzbhjpP", {"--RAW-CONTROL-CHARS", "--raw-control-chars",
             "--chop-long-lines", "--LINE-NUMBERS", "--line-numbers", "--quit-if-one-screen", "--no-init",
             "--ignore-case", "--IGNORE-CASE", "--squeeze-blank-lines", "--quiet", "--silent", "--no-lessopen"},
             set(), True),
    "more": ("dflcpsu", "n", {"--silent", "--logical", "--no-pause", "--print-over", "--clean-print", "--squeeze",
             "--plain"}, {"--lines"}, True),
}
"""The options a filter (or a reader fed by a pipe or xargs) may carry while a command names the sentinel or a
writer: none runs a program (sort --compress-program), reads a list of files or keys (--files0-from, less -k) or
writes a file (less -o/-O/--log-file; sort -o is a write target checked apart). A long option counts only spelled in
full, so no abbreviation (`--compress-prog`, `--c`) reaches one off the list; less takes no `+cmd` operand. cut, tr,
nl and column have no option that runs, reads a named list or writes, so they carry any."""


def _bulk_filter_runs(res):
    """True when a filter's (or fed reader's) options leave its allow-list (_BULK_FILTER_OPTS), when a fed git
    could run a program (_git_runs_bulk_name), or a fed rg, file or find runs or writes (--pre, -C, -exec ...)."""
    name = res.name
    vals = [w.value() for w in res.args]
    if name == "git":
        return _git_runs_bulk_name(res)
    if name == "rg":
        from lib.shell_parse import RG_PROGRAM_OPTS
        return any(v is None or v.split("=", 1)[0] in RG_PROGRAM_OPTS for v in vals)
    if name == "file":
        return any(v is None or v == "--compile" or re.fullmatch(r"-[A-Za-z]*C[A-Za-z]*", v) for v in vals)
    if name == "find":
        return any(v is None or v in _BULK_FIND_ACTIONS for v in vals)
    spec = _BULK_FILTER_OPTS.get(name)
    if spec is None:
        return False
    flags, valued, long_flags, long_valued, digits = spec
    k = 0
    while k < len(vals):
        v = vals[k]
        k += 1
        if v is None:
            return True
        if v == "--":
            break
        if name == "less" and v.startswith("+"):
            return True
        if v.startswith("--"):
            key = v.split("=", 1)[0]
            if key in long_valued:
                k += 0 if "=" in v else 1
            elif key not in long_flags or "=" in v:
                return True
            continue
        if not v.startswith("-") or v == "-":
            continue
        i = 1
        while i < len(v):
            ch = v[i]
            if ch in valued:
                k += 0 if i + 1 < len(v) else 1
                break
            if not (ch in flags or (digits and ch.isdigit())):
                return True
            i += 1
    return False


def _bulk_mentions(text):
    return bool(text) and any(name in text for name in BULK_NAMES)


def _bulk_word_mentions(w):
    return _bulk_mentions(w.text) or _bulk_mentions(w.value() or "")


_BULK_GLOB_SAFE = frozenset({"ls", "stat", "cat", "wc", "head", "tail", "grep", "egrep", "fgrep", "jq", "test", "[",
                             "cut", "nl", "column", "tr"})
"""Readers and filters with no option that runs a program or writes a file: a glob of theirs that could expand to
an option (`grep -l <name> *.py`) only changes what they read or print."""


def _bulk_static_args(name, args):
    """True when every word is a plain literal or a glob whose option, if any, is fixed by its literal text.

    A glob passes when its literal prefix is non-empty and does not start with `-` (`hooks/*.py`), spells a whole
    long option before `=` (`--include=*.py`, its key checked as a literal), follows a `--`, or belongs to a command
    of _BULK_GLOB_SAFE. A variable, a `${x:-..}` default, a brace expansion or a `$(..)`/backtick substitution can
    spell an option (find -exec/-fprintf, rg --pre, file -C, git --ext-diff/--output) that no literal check sees, so
    beside a protected name a reader or filter takes none."""
    ended = False
    for w in args:
        v = w.value()
        if v is not None:
            ended = ended or v == "--"
            continue
        if any(p.kind not in STATIC_PART_KINDS for p in w.parts):
            return False
        prefix = w.static_prefix()
        if ended or (prefix and not prefix.startswith("-")) or re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9-]*=.*", prefix):
            continue
        if name not in _BULK_GLOB_SAFE:
            return False
    return True


def _bulk_standalone(w):
    """A word that is the protected path or a writer script, not text that merely contains the name.

    A computed word that carries a name is read as the name: what it expands to is not known."""
    v = w.value()
    if v is None:
        return _bulk_mentions(w.text)
    for script in BULK_NAMES[1:]:
        if v == script or v.endswith("/" + script):
            return True
    return v.rsplit("/", 1)[-1].startswith(BULK_NAMES[0]) and not any(c in v for c in " \t\n")


_GIT_INERT_CONFIG_RE = re.compile(
    r"color\.[a-z]+(=(never|always|auto|true|false))?"
    r"|core\.pager=(%s)" % "|".join(sorted(_bash_read_only.PLAIN_PAGERS)) +
    r"|core\.(quotepath|abbrev)(=[a-z0-9]+)?"
    r"|log\.(abbrevcommit|decorate|follow|showroot|date)(=[a-z0-9:_-]*)?"
    r"|diff\.(renames|context|algorithm|colormoved|colormovedws|noprefix|mnemonicprefix|relative|interhunkcontext"
    r"|indentheuristic|statgraphwidth|suppressblankempty|wserrorhighlight)(=[a-z0-9,_-]*)?"
    r"|grep\.(patterntype|linenumber|column|extendedregexp|fullname)(=[a-z0-9_-]*)?"
    r"|status\.(showuntrackedfiles|short|branch|relativepaths|aheadbehind)(=[a-z0-9_-]*)?"
    r"|advice\.[a-z]+(=(true|false))?", re.IGNORECASE)
"""The exact `git -c` keys that only change how git prints: two segments, a value with no dot or path. Any other
setting (diff.external, diff.<driver>.textconv or .command, core.pager=<program>, core.editor, core.hooksPath,
core.sshCommand, include.path, alias.*, a filter or a credential helper, safe.directory ...) can make git run a
program or read another repository's config, so beside a protected name it is refused. The one key on the list that runs a
program, core.pager, is on it only with a value that reads (git_facts.GIT_RUN_CONFIG_KEY_RE holds the keys that run)."""


def _git_config_inert(setting):
    return setting is not None and bool(_GIT_INERT_CONFIG_RE.fullmatch(setting))



def _git_runs_bulk_name(res):
    """A git that names one of the names may run or write it.

    A name in git's global options (`-c alias.x=!...`, `-c core.pager=...`) is run later. Only a subcommand of
    _GIT_PLAIN reads what it is handed (`git config`, difftool -x, bisect run, submodule foreach, an alias, a
    computed subcommand all do not), and only without --output, --ext-diff or grep's -O / --open-files-in-pager
    (a long option's unique prefix counts, as git accepts it)."""
    args = list(res.args)
    k = 0
    while k < len(args):
        v = args[k].value()
        if v is None or not v.startswith("-"):
            break
        if _bulk_word_mentions(args[k]):
            return True
        if v.startswith("--exec-path=") or v.startswith("--config-env"):
            return True
        if v in GIT_GLOBAL_VALUE_OPTS and k + 1 < len(args):
            k += 1
            if _bulk_word_mentions(args[k]):
                return True
            if v == "-c" and not _git_config_inert(args[k].value()):
                return True
        k += 1
    if k >= len(args):
        return False
    sub = args[k].value()
    if sub not in _GIT_PLAIN:
        return True
    for w in args[k + 1:]:
        v = w.value() if w.value() is not None else w.text
        if v == "--":
            break
        if v.startswith("--") and len(v.split("=", 1)[0]) >= 4 and any(
                o.startswith(v.split("=", 1)[0]) for o in _GIT_RUN_OR_WRITE_OPTS):
            return True
        if sub == "grep" and v.startswith("-") and not v.startswith("--") and "O" in v:
            return True
    return False


def bulk_sentinel_decision(cmd):
    """PURE_READ, DENY or TOKENIZER_ERROR for a command naming the bulk-commit sentinel or its writers.

    The per-simple-command reading (_relaxed_bulk_sentinel_decision) decides only a command of the strict shape
    _relaxation_shape_ok accepts. Any other command gets the one-bare-read reading (_base_bulk_sentinel_decision)
    first: its refusal stands, and when it passes the per-command reading must pass too. Residual over-block: a
    compound, a function or a builtin capture next to a name is refused even when it only reads
    (`for f in hooks/*.py; do grep -l write-bulk-commit-sentinel.py "$f"; done`).
    """
    if _arg_write_named(cmd, _bulk_mentions):
        return 'DENY'
    if _relaxation_shape_ok(cmd, _bulk_mentions):
        return _relaxed_bulk_sentinel_decision(cmd)
    verdict = _base_bulk_sentinel_decision(cmd)
    if verdict != 'PURE_READ':
        return verdict
    return _relaxed_bulk_sentinel_decision(cmd)


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


def _base_bulk_sentinel_decision(cmd):
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
    if any(t in keywords or t in REDIRECT_OPS for t in tokens) or 'xargs' in tokens or 'tee' in tokens:
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




def _relaxed_bulk_sentinel_decision(cmd):
    """PURE_READ, DENY or TOKENIZER_ERROR for a command naming the bulk-commit sentinel or its writers.

    Each simple command lib/shell_parse.py's walk reaches (nested payloads included) is read on its own. One that
    names the path or a writer passes only as a reader (ls stat cat file wc head tail grep egrep fgrep rg jq find test
    [ git): not rg --pre or --hostname-bin, not file -C, not a find write or exec action, not git outside its plain
    read subcommands or with a run or output option (see _git_runs_bulk_name). A command whose arguments are code
    (sed, awk, eval, source, a shell or interpreter given -c/-e or a heredoc) or assignments (export, declare, local,
    readonly, typeset, alias, let) is refused when they carry a name; any other command when one of its words is the
    name itself (a name inside a longer argument is text). Refused too: a name in an assignment (a prefix one or one
    handed to env) or a wrapper's option, a for/select word list carrying one, `$_` (or BASH_REMATCH, BASH_COMMAND,
    BASH_ARGV) anywhere in a command that names one, a computed command beside a name, a non-filter fed by a pipe or
    xargs while the command names one, and a write target that names one or cannot be read. The
    sentinel is minted only by the userprompt-bulk-commit-capability hook, never from Bash. A command the parser
    cannot read is TOKENIZER_ERROR.
    """
    from lib.shell_parse import RG_PROGRAM_OPTS
    sites = _parsed_sites(cmd)
    if sites is None:
        return 'TOKENIZER_ERROR'
    named = _bulk_mentions(cmd)
    if named and _carries_last_arg(cmd):
        return 'DENY'
    if named:
        compounds = _compounds(cmd)
        if compounds is None or any(k.kind in LOOP_VAR_KINDS and any(_bulk_word_mentions(w) for w in k.header[1:])
                                    for k in compounds):
            return 'DENY'
    for site, res in sites:
        c = site.cmd
        words = _site_words(c)
        bodies = [r.hd.body for r in c.redirects if r.hd is not None]
        name = res.name
        bodies += [r.target.text for r in c.redirects if r.op == "<<<" and r.target is not None]
        fed = "pipe" in site.fed or any(n == "xargs" for n, _o in res.wrappers)
        if named and (site.dynamic or (fed and name not in _BULK_FILTERS)):
            return 'DENY'
        if named and (fed or name in _BULK_FILTERS - _BULK_READERS) and _bulk_filter_runs(res):
            return 'DENY'
        if named and name not in _BULK_FILTERS | _BULK_BENIGN and any(w.value() is None for w in res.args):
            return 'DENY'
        if named and name in _BULK_FILTERS and not _bulk_static_args(name, res.args):
            return 'DENY'
        if not (any(_bulk_word_mentions(w) for w in words) or any(_bulk_mentions(b) for b in bodies)):
            continue
        if any(_bulk_word_mentions(a.word) for a in tuple(c.assignments) + tuple(res.assignments)) or \
                site.templated or name is None:
            return 'DENY'
        if any(v is not None and _bulk_word_mentions(v) for _n, opts in res.wrappers for _o, v in opts):
            return 'DENY'
        if name in _BULK_CODE_ARG or name in _BULK_DECLARE or \
                any(_bulk_mentions(b) for b in bodies) and name not in _BULK_READERS:
            return 'DENY'
        if _BULK_INTERPRETER.fullmatch(name) and (res.payload is not None or any(
                re.fullmatch(r"-[a-zA-Z]*[ce][a-zA-Z]*", w.value() or "") for w in res.args)):
            return 'DENY'
        if name in _BULK_READERS:
            vals = [w.value() if w.value() is not None else w.static_prefix() for w in res.args]
            if name == "rg" and any(v.split("=", 1)[0] in RG_PROGRAM_OPTS for v in vals):
                return 'DENY'
            if name == "file" and any(v == "--compile" or re.fullmatch(r"-[A-Za-z]*C[A-Za-z]*", v) for v in vals):
                return 'DENY'
            if name == "find" and any(v in _BULK_FIND_ACTIONS for v in vals):
                return 'DENY'
            if name == "git" and _git_runs_bulk_name(res):
                return 'DENY'
            continue
        if any(_bulk_standalone(w) for w in [res.head] + list(res.args) + [r.target for r in c.redirects
                                                                           if r.target is not None]):
            return 'DENY'
    try:
        from lib.shell_parse import parse, write_targets
        targets = write_targets(parse(cmd))
    except Exception:  # noqa: BLE001
        return 'DENY'
    for t in targets:
        if _bulk_mentions(t.path or "") or (t.word is not None and _bulk_word_mentions(t.word)) or not t.decidable:
            return 'DENY'
    return 'PURE_READ'


def bulk_sentinel_rule(command):
    if not any(name in command for name in BULK_NAMES):
        return
    decision = bulk_sentinel_decision(command)
    if decision == 'TOKENIZER_ERROR':
        refuse("BLOCKED: bulk-commit-sentinel-write — the command could not be tokenized (likely an unterminated "
               "quote), so it is refused (fail-closed)", f"Command: {command}", released_line())
    elif decision != 'PURE_READ':
        refuse("BLOCKED: bulk-commit-sentinel-write — Bash command references the protected bulk sentinel path or a "
               "sentinel-writer script (write-bulk-commit-sentinel.py) in a write or run context — refused",
               f"Command: {command}",
               "REASON: the bulk-commit sentinel is minted only by the userprompt-bulk-commit-capability hook, never "
               "from Bash. A name passes only as an argument of a reader (ls|stat|cat|file|wc|head|tail|grep|egrep|"
               "fgrep|rg|jq|find|test|[ or a plain git read) with no rg --pre, file -C, find write or exec action, "
               "git global option, git --output/-O/difftool/bisect/submodule-style run, no write target, code (sed, "
               "awk, eval, -c, heredoc), assignment, env variable, for/select list or $_ carrying it, and no "
               "non-filter fed by a pipe or xargs, and no filter option that runs a program or reads or writes a named "
               "file (sort --compress-program, --files0-from, less -o).", released_line())


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


_HB_NOEXEC_SHELLS = ("bash", "sh", "dash")
_HB_SHELL_LONG = frozenset({"--norc", "--noprofile", "--noediting", "--posix", "--restricted", "--verbose", "--login"})
# The command word of a shell read as inert: written bare, or as an absolute path in a system bin directory.
_HB_SHELL_WORD = re.compile("(%s)?(%s)" % ("|".join(d + "/" for d in locations.BIN_DIRS),
                                            "|".join(_HB_NOEXEC_SHELLS)))
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
        if v in OPTION_ENDS:
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
    if r.op in DUP_OPS:
        return r.dup is not None or r.close
    return r.op in ("<", ">", ">>") and _hb_plain(r.target) and r.target.literal() == locations.NULL_DEVICE


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


def _hb_only_reads(command):
    """True when lib/bash_read_only.py proves the whole command read-only, a command word in a plain program directory
    (lib/locations.BIN_DIRS, as each rule here) read as its bare name: it runs nothing it chooses, so a name is only read."""
    try:
        from lib.bash_read_only import is_read_only
        from lib.shell_parse import parse, walk
        out = list(command)
        for w in filter(None, (site.cmd.head() for site in walk(parse(command), into=()))):
            if (name := w.text.rpartition("/"))[0] in locations.BIN_DIRS and name[2]:
                out[w.span[0]:w.span[1]] = name[2].rjust(len(w.text))
        return is_read_only("".join(out))
    except Exception:  # noqa: BLE001
        return False


def _dry_run_only(name, args):
    """`npm publish` and `kubectl apply|create`, which act on a registry or a cluster: the refusal text when the
    call is the real one, None when it is no such call or its dry run (npm `--dry-run`; kubectl `--dry-run=client`
    or `=server`, or the value as the next word). A word computed at run time proves no dry run."""
    if name == "npm" and next((a for a in args if a is None or not a.startswith("-")), "") in (None, "publish"):
        if "--dry-run" in args or "--dry-run=true" in args:
            return None
        return "npm publish runs only as its dry run (npm publish --dry-run)"
    if name == "kubectl" and ("apply" in args or "create" in args):
        pairs = zip(args, args[1:] + [None])
        if any(a in ("--dry-run=client", "--dry-run=server") or (a == "--dry-run" and b in ("client", "server"))
               for a, b in pairs):
            return None
        return "kubectl apply and kubectl create run only as their dry run (--dry-run=client or --dry-run=server)"
    return None


def outward_rule(command):
    """What acts beyond this machine with no undo: a real `npm publish`, `kubectl apply` or `kubectl create` (their
    dry runs run), and code fetched by an HTTP client (HTTP_CLIENTS: curl, wget, ...) piped into a shell
    (`curl -s URL | bash`). Read through the
    parser (lib/shell_parse.walk, resolve), so wrappers, `bash -c` and substitutions are seen; a shell fed by a
    heredoc, a file or another program's output, and `bash script.sh`, are not refused here."""
    from lib.shell_parse import SHELLS, SimpleCommand, _stdin_redirect, parse, resolve, walk
    sites = list(walk(parse(command)))
    scripts = {}
    for site in sites:
        scripts.setdefault(id(site.script), site.script)
        res = resolve(site.cmd) if isinstance(site.cmd, SimpleCommand) else None
        why = _dry_run_only(res.name, res.argv()) if res is not None else None
        if why:
            refuse(f"BLOCKED: {why}.", f"Command: {command}",
                   "REASON: a publish or a cluster change acts outside this machine and cannot be taken back; "
                   "its dry run shows the same result and runs.", released_line())
    for script in scripts.values():
        for pl, _sep in script.items:
            fetched = False
            for stage in pl.stages:
                res = resolve(stage) if isinstance(stage, SimpleCommand) else None
                if fetched and res is not None and res.name in SHELLS and res.payload_kind != "shell_c" \
                        and res.stdin_shell and _stdin_redirect(stage.redirects) is None:
                    refuse("BLOCKED: code fetched by curl, wget or another HTTP client is piped into a shell.",
                           f"Command: {command}",
                           "REASON: the code that would run is not in the command, so no rule can read it first. "
                           "Download it to a file, read it, then run the file (bash <file>).", released_line())
                fetched = fetched or (res is not None and res.name in HTTP_CLIENTS)


def hard_ban_rule(command):
    """Scripts that manage session state or restart daemons. A set CLAUDE_HARD_BANNED_SCRIPTS is '|'-separated EREs,
    each matched anywhere in a command that is not read-only as a whole (_hb_only_reads: a search, listing or print
    of the script's file runs nothing); unset, session-recovery and restart-all-sessions match only as the command word: in the
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
    elif _hb_only_reads(command):
        return
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


# The write mechanisms of lib/shell_parse.write_targets that put bytes into the named file: a redirection, tee,
# a cp, mv, install, rsync or ln destination, dd of=, curl -o, wget -O, sed -i, truncate. Removal and the mode,
# owner and ACL verbs neither read nor write a secret's bytes, so they are not this rule's.
_SENSITIVE_WRITERS = frozenset({"tee", "cp", "mv", "install", "rsync", "ln", "dd", "curl", "wget", "sed", "truncate"})
# The verbs that write what they read into another file: a listed name among their operands is a secret read
# into a file, as an argument of a command whose output is redirected into one is.
_SENSITIVE_COPIERS = frozenset(INTO_DIR_VERBS)
# The writers the base never judged without an output redirection: a source-code or Markdown/reST document operand
# of theirs (`sed -i ... src/password_reset.py`, `mv docs/password-reset.md docs/pw.md`) is no secret file
# (lib/sensitive_names.is_code_or_doc_operand).
_OPERAND_WRITERS = _SENSITIVE_COPIERS | {"sed"}
# The verbs whose source operand, copied into a path that is not sensitive, may be a template (`.env.example`).
_TEMPLATE_COPIERS = frozenset({"cp", "cat"})
# How each network client reads its options: which long options take a value and which take none, which short
# options take a value and which take none, and the long name of a short option whose effect matters. An option's
# value is a local path or data, never a URL (`curl -c http://../.env URL` writes ./.env); only a positional
# operand and curl's `--url` value are URLs. A long option may be abbreviated to a unique prefix (getopt_long,
# argparse): an ambiguous prefix may mean any option it begins, and an option or short letter the table does not
# know is taken as taking a value, so the word after it gets no URL role.
_CURL_LONG_VALUES = frozenset((
    "abstract-unix-socket alt-svc aws-sigv4 cacert capath cert cert-type ciphers config connect-timeout connect-to "
    "continue-at cookie cookie-jar create-file-mode crlfile curves data data-ascii data-binary data-raw "
    "data-urlencode delegation dns-interface dns-ipv4-addr dns-ipv6-addr dns-servers doh-url dump-header egd-file "
    "engine etag-compare etag-save expect100-timeout form form-string ftp-account ftp-alternative-to-user ftp-method "
    "ftp-port ftp-ssl-ccc-mode happy-eyeballs-timeout-ms header help hostpubmd5 hostpubsha256 hsts interface "
    "ipfs-gateway json keepalive-time key key-type krb libcurl limit-rate local-port login-options mail-auth "
    "mail-from mail-rcpt max-filesize max-redirs max-time netrc-file noproxy oauth2-bearer output output-dir "
    "parallel-max pass pinnedpubkey preproxy proto proto-default proto-redir proxy proxy-cacert proxy-capath "
    "proxy-cert proxy-cert-type proxy-ciphers proxy-crlfile proxy-header proxy-key proxy-key-type proxy-pass "
    "proxy-pinnedpubkey proxy-service-name proxy-tls13-ciphers proxy-tlsauthtype proxy-tlspassword proxy-tlsuser "
    "proxy-user proxy1.0 pubkey quote random-file range rate referer request request-target resolve retry "
    "retry-delay retry-max-time sasl-authzid service-name socks4 socks4a socks5 socks5-gssapi-service "
    "socks5-hostname speed-limit speed-time stderr telnet-option tftp-blksize time-cond tls-max tls13-ciphers "
    "tlsauthtype tlspassword tlsuser trace trace-ascii trace-config unix-socket upload-file url url-query user "
    "user-agent variable write-out").split())
_CURL_LONG_FLAGS = frozenset((
    "anyauth append basic ca-native cert-status compressed compressed-ssh create-dirs crlf digest disable "
    "disable-eprt disable-epsv disallow-username-in-url doh-cert-status doh-insecure fail fail-early fail-with-body "
    "false-start form-escape ftp-create-dirs ftp-pasv ftp-pret ftp-skip-pasv-ip ftp-ssl-ccc ftp-ssl-control get "
    "globoff haproxy-clientip haproxy-protocol head http0.9 http1.0 http1.1 http2 http2-prior-knowledge http3 "
    "http3-only ignore-content-length include insecure ipv4 ipv6 junk-session-cookies list-only location "
    "location-trusted mail-rcpt-allowfails manual metalink negotiate netrc netrc-optional next no-alpn no-buffer "
    "no-clobber no-keepalive no-npn no-progress-meter no-sessionid ntlm ntlm-wb parallel parallel-immediate "
    "path-as-is post301 post302 post303 progress-bar proxy-anyauth proxy-basic proxy-ca-native proxy-digest "
    "proxy-http2 proxy-insecure proxy-negotiate proxy-ntlm proxy-ssl-allow-beast proxy-ssl-auto-client-cert "
    "proxy-tlsv1 proxytunnel raw remote-header-name remote-name remote-name-all remote-time remove-on-error "
    "retry-all-errors retry-connrefused sasl-ir show-error silent socks5-basic socks5-gssapi socks5-gssapi-nec ssl "
    "ssl-allow-beast ssl-auto-client-cert ssl-no-revoke ssl-reqd ssl-revoke-best-effort sslv2 sslv3 styled-output "
    "suppress-connect-headers tcp-fastopen tcp-nodelay tftp-no-options tlsv1 tlsv1.0 tlsv1.1 tlsv1.2 tlsv1.3 "
    "tr-encoding trace-ids trace-time use-ascii verbose version xattr").split())
_WGET_LONG_VALUES = frozenset((
    "execute output-file append-output report-speed input-file base config rejected-log tries "
    "retry-on-http-error output-document start-pos progress timeout dns-timeout connect-timeout read-timeout wait "
    "waitretry quota bind-address limit-rate restrict-file-names prefer-family user password use-askpass "
    "local-encoding remote-encoding directory-prefix cut-dirs http-user http-password default-page header "
    "compression proxy-user proxy-password referer user-agent load-cookies save-cookies post-data post-file method "
    "body-data body-file secure-protocol certificate certificate-type private-key private-key-type ca-certificate "
    "ca-directory crl-file pinnedpubkey random-file ciphers ftp-user ftp-password warc-file warc-header "
    "warc-max-size warc-dedup warc-tempdir level backups accept reject accept-regex reject-regex regex-type domains "
    "exclude-domains follow-tags ignore-tags include-directories exclude-directories hsts-file max-redirect").split())
_WGET_LONG_FLAGS = frozenset((
    "adjust-extension ask-password auth-no-challenge background backup-converted content-disposition "
    "content-on-error continue convert-file-only convert-links debug delete-after follow-ftp force-directories "
    "force-html ftps-clear-data-connection ftps-fallback-to-ftp ftps-implicit ftps-resume-ssl help https-only "
    "ignore-case ignore-length inet4-only inet6-only keep-session-cookies mirror no-cache no-check-certificate "
    "no-clobber no-config no-cookies no-directories no-dns-cache no-glob no-host-directories no-hsts "
    "no-http-keep-alive no-if-modified-since no-iri no-netrc no-parent no-passive-ftp no-proxy no-remove-listing "
    "no-use-server-timestamps no-verbose no-warc-compression no-warc-digests no-warc-keep-log page-requisites "
    "preserve-permissions protocol-directories quiet random-wait recursive relative retr-symlinks "
    "retry-connrefused retry-on-host-error save-headers server-response show-progress span-hosts spider "
    "strict-comments timestamping trust-server-names unlink verbose version warc-cdx xattr").split())
_HTTPIE_LONG_VALUES = frozenset((
    "boundary raw pretty style response-charset response-mime format-options print history-print output session "
    "session-read-only auth auth-type proxy max-redirects max-headers timeout verify ssl ciphers cert cert-key "
    "cert-key-pass default-scheme bearer http-version resolve interface unix-socket generate").split())
_HTTPIE_LONG_FLAGS = frozenset((
    "json form multipart compress unsorted sorted headers meta body verbose all stream download continue quiet "
    "ignore-netrc offline follow check-status path-as-is chunked ignore-stdin help manual version traceback debug "
    "native-tls https curl curl-long ipv4 ipv6").split())
_ARIA2C_LONG_VALUES = frozenset((
    "out dir input-file log conf-path save-session load-cookies save-cookies header user-agent referer "
    "max-connection-per-server split").split())
_ARIA2C_LONG_FLAGS = frozenset("continue quiet help version check-integrity force-sequential".split())
# Per client: (long options with a value, long options without one, short options with a value, short options
# without one, short option -> long name where its effect matters).
_HTTPIE_OPTIONS = (_HTTPIE_LONG_VALUES, _HTTPIE_LONG_FLAGS, "pPosaA", "jfmhbvdcqSFxI46",
                   {"o": "output", "d": "download"})
_CLIENT_OPTIONS = {
    "curl": (_CURL_LONG_VALUES, _CURL_LONG_FLAGS, "EKCbcdDFPHhmoxUQreXYytzTuAw", "aqfGgI0ik46jlLMn:NZ#pJORSs231BvV",
             {"o": "output", "O": "remote-name", "J": "remote-header-name", "g": "globoff", "K": "config"}),
    "wget": (_WGET_LONG_VALUES, _WGET_LONG_FLAGS, "aABDeiIlOoPQRtTUwX", "VhbdqvFcNS46xErkKmpHL",
             {"O": "output-document"}),
    "aria2c": (_ARIA2C_LONG_VALUES, _ARIA2C_LONG_FLAGS, "dDoiIlsxkjtmuU", "cqZVhv",
               {"o": "out", "Z": "force-sequential", "i": "input-file"}),
    "http": _HTTPIE_OPTIONS, "https": _HTTPIE_OPTIONS, "httpie": _HTTPIE_OPTIONS, "xh": _HTTPIE_OPTIONS,
}
# The network clients whose non-output arguments may be URLs (a URL there names no local file): those
# _CLIENT_OPTIONS reads.
_NETWORK_CLIENTS = frozenset(_CLIENT_OPTIONS)
_HTTPIE_CLIENTS = frozenset({"http", "https", "httpie", "xh"})
# curl's URL globbing (`{a,b}`, `[1-3]`) and aria2c's parameterized URIs: with them an output name may be built from
# the URL (`curl "https://x/{.env}" -o "#1"` writes ./.env).
_URL_GLOB = re.compile(r"[{}\[\]]")


def _resolve_long(name, values, flags):
    """(the long options a possibly abbreviated name may mean, whether it may take a value). An exact name is
    itself; a prefix may mean every option it begins; a name no option begins is taken as taking a value."""
    known = values | flags
    if name in known:
        return {name}, name in values
    if name.startswith("expand-") and name[7:] in known:  # curl's --expand-<option>
        return {name[7:]}, name[7:] in values
    cands = {k for k in known if k.startswith(name)}
    if not cands and name.startswith("no-") and name[3:] in flags:
        return {name[3:]}, False
    return cands, (not cands) or bool(cands & values)


def _client_args(client, values):
    """Read a network client's argument values (None for a word computed at run time) by its option table.

    Returns (options, urls, closed): `options` lists (set of long names it may mean, value or None); `urls` maps the
    index of each positional operand and of each curl `--url` value to its URL text; `closed` is True when an httpie
    or xh short-option cluster holds `d` beside a letter the table does not know, which takes the URL exemption
    from the whole command. A computed word may be an option taking the next word: that word gets no URL role."""
    long_values, long_flags, short_values, short_flags, short_long = _CLIENT_OPTIONS[client]
    options, urls, closed = [], {}, False
    i, n, operands_only = 0, len(values), False
    while i < n:
        v = values[i]
        if v is None:
            i += 2
            continue
        if operands_only or v == "-" or v[:1] != "-":
            urls[i] = v
            i += 1
            continue
        if v == "--":
            operands_only = True
            i += 1
            continue
        if v.startswith("--"):
            body, eq, inline = v[2:].partition("=")
            cands, takes = _resolve_long(body, long_values, long_flags)
            value = None
            if eq:
                value = inline
                if cands == {"url"}:
                    urls[i] = inline
            elif takes:
                value = values[i + 1] if i + 1 < n else None
                if cands == {"url"} and value is not None:
                    urls[i + 1] = value
                i += 1
            options.append((cands, value))
            i += 1
            continue
        cluster, k = v[1:], 0
        while k < len(cluster):
            c = cluster[k]
            if client == "wget" and c == "n":  # -nv, -nc, -nd, -nH: `n` and the letter after it
                k += 2
                continue
            names = {short_long.get(c, "-" + c)}
            if c in short_values or c not in short_flags:
                if c not in short_values and client in _HTTPIE_CLIENTS and "d" in cluster:
                    closed = True
                value = cluster[k + 1:]
                if not value:
                    value = values[i + 1] if i + 1 < n else None
                    i += 1
                options.append((names, value))
                break
            options.append((names, None))
            k += 1
        i += 1
    return options, urls, closed


def _network_output(name, values):
    """(writes, url_names_it, urls) for a network client's argument values: whether it writes a file of its own,
    whether that file is named after the URL (wget without -O/--output-document or with one other than `-`; curl
    -O, --remote-name, --remote-name-all or -J; aria2c without -o/--out; http, https, httpie or xh with -d or
    --download, in a cluster or abbreviated, and no -o/--output), and its URL operands by word index
    (_client_args). An option that may mean one naming the output is taken as naming it, so the caller keeps its
    check rather than lifting it. A config file can turn such an option on (a curl config holding `remote-name`),
    so curl -K/--config, wget --config and aria2c --conf-path name the output after the URL, and so does httpie
    or xh without -o/--output, whose default options file can add --download."""
    options, urls, closed = _client_args(name, values)

    def may(opt):
        return any(opt in names for names, _ in options)

    def last(opt):
        found = [val for names, val in options if names == {opt}]
        return found[-1] if found else None

    # An output value holding `#` may be a curl glob reference (`-o "#1"`): taken as naming the output after the
    # URL, in every client. A URL holding a glob or parameter character is taken so too, unless curl's globbing is
    # off by -g or --globoff (and no word spells a `--no-` option, which might turn it back on).
    hashed = any(names & {"output", "output-document", "out"} and val is not None and "#" in val
                 for names, val in options)
    globbed = any(_URL_GLOB.search(u) for u in urls.values())
    if name == "curl":
        globoff = any(names == {"globoff"} for names, _ in options) \
            and not any(v is not None and v.startswith("--no-") for v in values)
        named = may("remote-name") or may("remote-name-all") or may("remote-header-name") or may("config") \
            or hashed or (globbed and not globoff)
        to_file = any("output" in names and val != "-" for names, val in options)
        return named or to_file, named, urls
    if name == "wget":
        document = last("output-document")
        unsure = any("output-document" in names and len(names) > 1 for names, _ in options)
        return document != "-", document is None or unsure or hashed or may("config"), urls
    if name == "aria2c":
        # -Z/--force-sequential downloads each URI under its own name whatever -o says; -i/--input-file reads URIs
        # and per-URI options from a file; a parameterized URI expands into several.
        sequential = may("force-sequential") or may("input-file") or may("conf-path")
        return True, last("out") is None or sequential or hashed or globbed, urls
    download = may("download")
    output = last("output") is not None
    return download or output, closed or hashed or not output, urls


# The options of cp, mv, ln, install and rsync that take a value as the next word (or the rest of a short cluster):
# that value is no source operand. An option not listed is taken as taking none, so the word after it is judged.
_COPY_OPTIONS = {
    "cp": (frozenset({"target-directory", "suffix"}), "tS"),
    "mv": (frozenset({"target-directory", "suffix"}), "tS"),
    "ln": (frozenset({"target-directory", "suffix"}), "tS"),
    "install": (frozenset({"target-directory", "suffix", "mode", "owner", "group", "strip-program"}), "tSmog"),
    "rsync": (frozenset((
        "exclude include exclude-from include-from files-from filter rsh rsync-path log-file log-file-format "
        "partial-dir temp-dir compare-dest copy-dest link-dest backup-dir suffix chmod chown usermap groupmap "
        "timeout contimeout bwlimit max-size min-size max-delete modify-window password-file port sockopts "
        "out-format info debug protocol iconv checksum-choice compress-choice compress-level skip-compress "
        "block-size stop-after stop-at write-batch only-write-batch read-batch outbuf remote-option address "
        "checksum-seed max-alloc early-input").split()), "efTBM"),
}


def _copier_operands(name, words):
    """(index, Word) of each operand of a cp, mv, ln, install or rsync, its option words and their values aside. A
    computed word is kept as an operand."""
    longs, shorts = _COPY_OPTIONS.get(name, (frozenset(), ""))
    out, i, only = [], 0, False
    while i < len(words):
        v = words[i].value()
        if only or v is None or v == "-" or v[:1] != "-":
            out.append((i, words[i]))
        elif v == "--":
            only = True
        elif v.startswith("--"):
            body, eq, _ = v[2:].partition("=")
            if not eq and body in longs:
                i += 1
        else:
            for k, c in enumerate(v[1:], 1):
                if c in shorts:
                    if k + 1 == len(v):
                        i += 1
                    break
        i += 1
    return out


def _local_url(value):
    """True when a network client's argument is a `file:` URL, any case: a local file it reads."""
    return bool(value) and value[:5].lower() == "file:"


def _word_sensitive(w, **roles):
    """lib/sensitive_names.py's verdict on a Word: its static value with the exemptions `roles` allows, or its raw
    text when computed."""
    from lib.sensitive_names import is_sensitive_name
    v = w.value()
    return is_sensitive_name(v, **roles) if v is not None else is_sensitive_name(w.text, computed=True)


def _code_copy(t):
    """True when a copy, move or link writes a code file from a code file (`cp src/password.ts dist/password.ts`)
    into a directory that carries no secret word."""
    from lib.sensitive_names import base_name, is_code_file, is_sensitive_name
    if t.mechanism not in _SENSITIVE_COPIERS or not (t.source and is_code_file(t.source) and is_code_file(t.path)):
        return False
    head = t.path[:len(t.path) - len(base_name(t.path))]
    return not is_sensitive_name(head)


def _command_name(cmd):
    try:
        from lib.shell_parse import resolve
        return resolve(cmd).name
    except Exception:  # noqa: BLE001
        return None


def sensitive_redirect(command, kept=False):
    """BS-20/21 (audit BS-10/11). 'write' when a command writes a file lib/sensitive_names.py calls sensitive (a
    redirection into it, or tee, cp, mv, install, rsync, ln, dd of=, curl -o, wget -O, sed -i or truncate naming
    it), 'redirect' when such a name is a word or an input redirection of a command whose output goes to a file, or
    a source operand of cp, mv, install, rsync or ln other than a source-code file; None otherwise. A word counts
    only where it can be a source: not a grep or rg pattern, not echo's or printf's static text, and a command line
    a shell or a runner (docker exec, ssh, watch ...) is handed is read as the commands it holds, their output kept
    (``kept``) as its own is.

    Read from lib/shell_parse.py's parsed commands, payloads included (eval, bash -c, a heredoc-fed shell), so a
    name inside quoted data or a heredoc body that no command reads as a path is data. The full path text is judged
    by substring with lib/sensitive_names.py's narrow exemptions, each only where its role allows: a test file
    anywhere; a report, log or template as a write target; a template as a cp or cat source; a URL as a network
    client's positional operand or curl `--url` value whose output file it does not name (not `file:`, not
    host-less, not host `.` or `..`; not with an output value holding `#`, a curl URL holding `{`, `}`, `[` or `]`
    without -g/--globoff, nor aria2c without -o or with -Z/--force-sequential, -i/--input-file, --conf-path or a
    parameterized URI, nor curl -K/--config or wget --config, nor httpie or xh without -o/--output), never as an
    option's value, a redirection or write target or another
    command's operand; a `file:` URL a network client reads into its own output file
    (curl -o, wget -O) is a secret read; a code file copied onto a code-file name; a source-code or Markdown/reST
    operand of cp, mv, install, rsync, ln or sed -i (is_code_or_doc_operand). A computed word (`$X`, `$(...)`, a glob) and interpreter code are judged by substring on
    their raw text. A command the parser cannot read is judged on its raw text by substring, so it is refused more,
    never less.
    """
    from lib.sensitive_names import (RAW_FALLBACK_READ, RAW_FALLBACK_WRITE, is_code_file, is_code_or_doc_operand,
                                     is_sensitive_name)
    try:
        from lib.bash_read_only import is_read_only
        from lib.shell_parse import SHELLS, _DEFAULT_INTO, parse, resolve, walk, write_targets
        script = parse(command)
        if script.error is not None:
            raise ValueError(script.error.code)
        for t in write_targets(script, into=_DEFAULT_INTO):
            writer = t.mechanism.startswith("redirect") or t.mechanism.split("-", 1)[0] in _SENSITIVE_WRITERS
            if not writer or t.mode == "delete":
                continue
            if t.path is not None:
                if t.mechanism.split("-", 1)[0] in _OPERAND_WRITERS and is_code_or_doc_operand(t.path):
                    continue
                if is_sensitive_name(t.path, report=True, template=True) and not _code_copy(t):
                    return "write"
            elif t.word is not None and _word_sensitive(t.word):
                return "write"
        for site in walk(script):
            redirs = [r for r in site.cmd.redirects if r.target is not None]
            outputs = [r for r in redirs if r.writes()]
            if any(_word_sensitive(r.target, report=True, template=True) for r in outputs):
                return "write"
            name = _command_name(site.cmd)
            network = name in _NETWORK_CLIENTS
            writes, url_names_output, urls = (_network_output(name, [w.value() for w in site.cmd.words[1:]])
                                              if network else (False, False, {}))
            if any(r.fd == 1 or r.op in BOTH_STREAMS_OPS for r in outputs) and tuple(site.context) == ("top",) \
                    and is_read_only(command[slice(*site.cmd.span)]):
                outputs = []  # lib/bash_read_only.py's reader, its output thrown into /dev/null: what it reads lands nowhere
            if not outputs and network and writes:
                # A client writing its own output file reads a `file:` URL into it (curl file:///.env -o /tmp/y).
                if any(_local_url(w.value()) and _word_sensitive(w) for w in site.cmd.words[1:]):
                    return "redirect"
                continue
            if outputs or kept:
                args = resolve(site.cmd).args
                texts = [w.text if w.value() is None else w.value() for w in args]
                spec = {"grep": _SD_GREP, "egrep": _SD_GREP, "fgrep": _SD_GREP, "rg": _SD_RG}.get(name)
                data = _sd_scan(texts, spec) or () if spec else range(len(args)) if name in PRINTERS else ()
                skip = {id(args[k]) for k in data if k < len(args) and (spec or args[k].value() is not None)}
                for w in args if name in SHELLS or name in _OPAQUE_RUNNERS else ():
                    if any(c.isspace() for c in w.value() or "") and parse(w.value()).error is None:
                        inner = sensitive_redirect(w.value(), True)
                        if inner:
                            return inner
                        skip.add(id(w))
                words = [(i, w) for i, w in enumerate(site.cmd.words[1:]) if id(w) not in skip]
            elif name in _SENSITIVE_COPIERS:
                # A copy's source operands, its options and their values aside (`rsync --exclude .env`): a
                # source-code file is no secret read (its destination was judged above).
                words = [(i, w) for i, w in _copier_operands(name, site.cmd.words[1:])
                         if not is_code_file(w.value()) and not is_code_or_doc_operand(w.value())]
            else:
                continue
            # The destination was judged above, so a cp or cat source here is copied into a path that is not
            # sensitive. A URL is a network client's positional operand or curl `--url` value only, never an
            # option's value (`curl -c http://../.env URL` writes ./.env), another command's operand, nor one that
            # names the client's output file (wget https://x/.env > /tmp/log writes ./.env).
            url_role = network and not url_names_output
            template = name in _TEMPLATE_COPIERS

            def sensitive(i, w):
                if url_role and i in urls and w.value() is not None:
                    return is_sensitive_name(urls[i], url=True)
                return _word_sensitive(w, template=template)

            if any(sensitive(i, w) for i, w in words) \
                    or any(_word_sensitive(r.target) for r in redirs if not r.writes()):
                return "redirect"
        return None
    except Exception:  # noqa: BLE001
        if grep(RAW_FALLBACK_WRITE, command):
            return "write"
        if grep(RAW_FALLBACK_READ, command):
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


# The command-position reading (OB-L11): each rule reads the command word lib/shell_parse.py resolves (wrappers
# such as sudo, xargs, env, timeout and path forms peeled; eval, `bash -c`, heredoc shells, find -exec read as
# commands) and that simple command's own arguments and redirections, so a search for the words is data. Text the
# parser hands on unread keeps the raw reading: an interpreter's code (python -c, node -e, a heredoc fed to one)
# for the raw-text rules, a runner's command line (watch, tmux, docker exec ...) for every rule. A command the parser
# cannot read statically (a parse error, a computed command word or payload) is read as before, on its raw text.

_CODE_CARRIER = re.compile(r"^(python[\d.]*|pypy[\d.]*|node|nodejs|deno|bun|perl[\d.]*|ruby[\d.]*|php[\d.]*|lua[\d.]*"
                           r"|luajit|tclsh[\d.]*|wish|osascript|Rscript|[gmn]?awk)$")
_CODE_OPTS = frozenset({"-c", "-e", "-E", "-p", "-r", "--eval", "--print", "-x"})
_OPAQUE_RUNNERS = frozenset({"watch", "parallel", "script", "bwrap", "machinectl", "start-stop-daemon", "coproc",
                             "tmux", "screen", "at", "batch", "docker", "podman", "nerdctl", "kubectl", "lxc", "incus",
                             "vagrant", "expect", "gdb", "entr", "dtach", "abduco", "busctl", "dbus-send", "su", "sg",
                             "runuser", "ssh", "pkexec", "sudoedit"})
DOCKER_DAEMON_JSON = "/etc/docker/daemon.json"
WORKFLOW_STATE_RE = r"(workflow-[^/]*\.json|\.claude/todos/)"
DD_DEV_OK = ("null", "zero", "stdout", "stderr")


class ServiceView:
    """The simple commands of a command, resolved, for the service, disk, process and workflow rules.

    raw: True when the parser cannot read the command statically; the rules then read the raw text as before.
    sites: (name, args Words, Site, Resolved) per simple command that has a command word; redirect_sites: every Site.
    code: interpreter code texts; runners: opaque runners' command lines (both read by the raw-text rules).
    """

    def __init__(self, command, cwd=None):
        self.raw, self.sites, self.code, self.runners, self.redirect_sites = False, [], [], [], []
        self.exec_redirects, self.plain, self.command, self.sets = [], False, command, {}
        self.cwd = cwd if isinstance(cwd, str) and cwd else os.getcwd()
        try:
            from lib.shell_parse import _AssignScope, parse, resolve, walk
            script = parse(command)
            if script.error is not None:
                raise ValueError(script.error.code)
            nested, scope = False, _AssignScope(script)
            for site in walk(script):
                r = resolve(site.cmd)
                if site.dynamic or site.templated or (r.unresolved and not str(r.unresolved).startswith("xargs_")):
                    self.raw = True
                nested = nested or tuple(site.context) != ("top",)
                self.redirect_sites.append(site)
                if not site.cmd.words and tuple(site.context) == ("top",) and scope.certain(site, site.cmd):
                    self.sets.update((a.name, (a.word.span[0], a.static_value())) for a in site.cmd.assignments
                                     if a.static_value() and not a.append)
                if [w.value() for w in site.cmd.words] == ["exec"]:
                    self.exec_redirects.extend(site.cmd.redirects)  # they hold for every later command
                name = r.name
                if name is None:
                    continue
                args = list(r.args)
                self.sites.append((name, args, site, r))
                bodies = [x.hd.body for x in site.cmd.redirects if x.hd is not None] + \
                         [x.target.text for x in site.cmd.redirects if x.op == "<<<" and x.target is not None]
                line = " ".join([r.head.text] + [w.text for w in args] + bodies)
                if _CODE_CARRIER.match(name):
                    self.code.append(line)
                    vals = [w.value() for w in args]
                    reads_stdin = not any(v is None or v in _CODE_OPTS or not v.startswith("-") for v in vals)
                    if reads_stdin and ({"pipe", "file"} & set(site.fed)):
                        self.raw = True  # its program is another command's output
                elif name in _OPAQUE_RUNNERS:
                    self.runners.append(line)
            self.plain = not (self.raw or nested or self.code or self.runners) and _plain_script(script, self)
        except Exception:  # noqa: BLE001 - the parser unavailable or the text unreadable: the raw reading
            self.raw, self.plain = True, False

    def named(self, *names):
        return [(n, a, s, r) for n, a, s, r in self.sites if n in names]

    def set_once(self, word, at, rx):
        """True for a word that ends in one bare `$name` (or `${name}`) whose name the command sets once, to a static
        value `rx` matches whole, unconditionally and before offset `at`, and names nowhere else but as `$name`, and
        which sources and evals nothing: nothing else can have set it."""
        p = word.parts[-1]
        n = re.escape(p.text)
        where, value = self.sets.get(p.text, (at, "")) if p.kind == "param" else (at, "")
        return where < at and re.fullmatch(rx, value) is not None and not self.named("source", ".", "eval") \
            and len(re.findall(rf"(?<![A-Za-z0-9_]){n}(?![A-Za-z0-9_])", self.command)) \
            == 1 + len(re.findall(rf"\$(?:{n}(?![A-Za-z0-9_])|\{{{n}\}})", self.command))

    def without(self, view, name, whole):
        """`view` without the `name` commands the command-position reading reads whole (`whole(cmd, self)`): the
        command word of an unwrapped simple command at the top level (inside if, for, while and until too), where
        the program runs, so the raw reading of the rest of the command has nothing to add about it."""
        out = list(view)
        for _n, _a, site, r in self.named(name) if not self.raw and len(view) == len(self.command) else ():
            words = site.cmd.words
            if tuple(site.context) == ("top",) and not (site.cmd.assignments or r.wrappers or r.payload is not None
                                                        or r.unresolved) and whole(site.cmd, self) \
                    and _plain_redirects(site.cmd, self, reads_ok=False):
                out[words[0].span[0]:words[-1].span[1]] = " " * (words[-1].span[1] - words[0].span[0])
        return "".join(out)


# The plain shape. Only a command made wholly of these simple commands, each with static arguments and plain
# redirections, is read at command position alone; every other command also keeps the pre-OB-L11 whole-command
# readings (service_rules, kill_pid_rule), so a launcher, wrapper or payload the parser does not classify (uv run,
# npx, nsenter, git -c alias.x='!..', git rebase --exec, PAGER=..) loses no refusal the rules had before.
_PLAIN_READERS = frozenset({"grep", "egrep", "fgrep", "rg", "sed", "jq", "cat", "head", "tail", "ls", "echo",
                            "printf", "wc"})
_KILL_PROBE_OPTS = ("-0", "-l", "-L")  # kill -0 probes a pid, -l / -L list the signals: nothing is sent
_PLAIN_FILTERS = frozenset({"grep", "egrep", "fgrep", "rg", "sed", "jq", "cat", "head", "tail", "wc"})
_PLAIN_GIT_READS = frozenset({"log", "show", "diff", "status", "grep", "blame", "rev-parse", "ls-files", "ls-tree",
                              "cat-file", "shortlog", "describe", "rev-list"})
_SED_PRINT = re.compile(r"^(([0-9]+|\$)(,([0-9]+|\$))?)?p$")


def _plain_word(w, params=False):
    """A static word (literal or glob), or with `params` a parameter expansion holding no command substitution."""
    kinds = ("lit", "glob", "param") if params else ("lit", "glob")
    return all(p.kind in kinds for p in w.parts) and not w.substitutions()


def _abs_norm(path, cwd="/"):
    """The absolute normal form of a path: normpath keeps a leading `//` (POSIX leaves its meaning to the system;
    Linux reads it as `/`), so the leading slashes are collapsed too."""
    p = os.path.normpath(path if path.startswith("/") else os.path.join(cwd, path))
    return "/" + p.lstrip("/") if p.startswith("/") else p


def _plain_file(w, sv):
    """An ordinary file (not under /dev, /proc, /sys, /etc ...) or /dev/null, named statically."""
    v = w.value() if _plain_word(w) else None
    if not v or v.startswith("~"):
        return False
    p = _abs_norm(v, sv.cwd)
    if not v.startswith("/") and sv.named("cd", "pushd", "popd"):
        return False
    return all(q == locations.NULL_DEVICE or not locations.is_system_path(q)
               for q in (p, _abs_norm(os.path.realpath(p))))


def _plain_redirects(cmd, sv, reads_ok=True):
    """Writes on fd 1 or 2 (or &>) to an ordinary file or /dev/null, 2>&1, >&2, N>&-; with `reads_ok` also a read
    on fd 0 of a static file and a heredoc or here-string that expands nothing."""
    for x in cmd.redirects:
        if x.fd_var is not None:
            return False
        if x.op in HEREDOC_OPS:
            if not reads_ok or x.fd != 0:
                return False
            if x.hd is not None and not (x.hd.quoted or not x.hd.expansions):
                return False
            if x.op == "<<<" and not (x.target is not None and _plain_word(x.target)):
                return False
        elif x.close:
            continue
        elif x.op in DUP_OPS and x.dup is not None:
            if x.fd not in (1, 2) or x.dup not in (1, 2):
                return False
        elif x.op == "<":
            if not reads_ok or x.fd != 0 or x.target is None or not _plain_word(x.target):
                return False
        elif x.op in OUTPUT_REDIRECT_OPS:
            if x.fd not in (1, 2, None) or x.target is None or not _plain_file(x.target, sv):
                return False
        else:
            return False  # <>, a computed >& target
    return True


def _plain_dd(vals, sv):
    """dd with static operands only, each of= /dev/null, /dev/stdout, /dev/stderr, /dev/fd/N or an ordinary file."""
    if not all(v is not None and v.startswith(_DD_OPERANDS) for v in vals):
        return False
    for v in vals:
        if not v.startswith("of="):
            continue
        path = v[3:]
        if path.startswith("/") and _abs_norm(path) in locations.STD_SINKS:
            continue
        if not path or path.startswith("~") or (not path.startswith("/") and sv.named("cd", "pushd", "popd")):
            return False
        p = _abs_norm(path, sv.cwd)
        if locations.FD_PATH.match(p):
            continue  # its command's redirections are plain (fd 1 and 2 only), so N is inherited or stdout/stderr
        if locations.is_system_path(p):
            return False
        if _dd_target_refused(path, sv):
            return False
    return True


def _plain_git(words):
    """A git read subcommand, past only -C DIR and inert flags; no -c, --config-env, alias, pager or output."""
    vals = [w.value() if _plain_word(w) else None for w in words]
    if None in vals:
        return False
    k = git_plain_subcommand_index(vals, GIT_INERT_FLAGS)
    if k is None or vals[k] not in _PLAIN_GIT_READS:
        return False
    return not any(v.startswith(_GIT_RUN_OR_WRITE_PREFIXES) or re.match(r"^-[A-Za-z]*O", v) for v in vals[k + 1:])


def _plain_simple(cmd, sv, piped):
    from lib.shell_parse import resolve
    if cmd.assignments or not cmd.words or not _plain_word(cmd.words[0]):
        return False
    name = cmd.words[0].value()
    if not name or "/" in name:
        return False
    r = resolve(cmd)
    if r.name != name or r.wrappers or r.payload is not None or r.unresolved or len(r.args) != len(cmd.words) - 1:
        return False
    args = list(cmd.words[1:])
    vals = [w.value() if _plain_word(w) else None for w in args]
    if piped and name not in _PLAIN_FILTERS:
        return False
    if name == "kill":  # a probe or a listing of literal words, or `kill -0 "$PID"` alone
        return bool(vals) and vals[0] in _KILL_PROBE_OPTS and _plain_kill_args(args[1:]) \
            and _plain_redirects(cmd, sv, reads_ok=False)
    if name == "dd":
        return _plain_dd(vals, sv) and _plain_redirects(cmd, sv, reads_ok=False)
    if name == "fdisk":
        opts = [v for v in vals if v is None or v.startswith("-")]
        return None not in vals and bool(opts) and all(
            v in _FDISK_READS or re.match(r"^-[A-Za-z]*l[A-Za-z]*$", v) for v in opts) \
            and _plain_redirects(cmd, sv, reads_ok=False)
    if name == "git":
        return _plain_git(args) and _plain_redirects(cmd, sv)
    if name not in _PLAIN_READERS or None in vals:
        return False
    if name == "rg" and any(v.startswith("--pre") for v in vals):
        return False
    if name == "sed":
        opts = [v for v in vals if v.startswith("-")]
        rest = [v for v in vals if not v.startswith("-")]
        if not opts or any(v not in SED_QUIET_OPTS for v in opts) or not rest \
                or not _SED_PRINT.match(rest[0]):
            return False
    return _plain_redirects(cmd, sv)


def _plain_kill_args(words):
    """bash's kill reads -s SIG and -n NUM (attached too) after -0, -l or -L, so `kill -0 ${X:--s} KILL 4242` and
    `kill -0 "$A" 4242` (A=-sKILL) send SIGKILL: only literal words stay plain, or one double-quoted bare parameter
    as the sole word (one word, so it cannot be an option and a PID)."""
    if all(p.kind == "lit" for w in words for p in w.parts) and not any(w.substitutions() for w in words):
        return True
    return len(words) == 1 and len(words[0].parts) == 1 and words[0].parts[0].kind == "param" \
        and words[0].parts[0].quote == "double" and re.match(r"^([A-Za-z_][A-Za-z0-9_]*|[0-9])$", words[0].parts[0].text) \
        and not words[0].substitutions()


def _dd_whole(cmd, sv):
    """dd that only reads: every word is one of its own operands and none is of=, so its output goes to standard
    output alone (a pipe, or the plain redirection `without` asks for). A word is static, or an operand name and one
    `$name` the command sets once to a plain path (ServiceView.set_once), which no splitting turns into an of=."""
    return all(w.static_prefix().startswith(_DD_OPERANDS) and not w.static_prefix().startswith("of=") and (
        w.value() is not None or len(w.parts) == 2 and sv.set_once(w, cmd.span[0], "[A-Za-z0-9_.,:+@%/-]+"))
        for w in cmd.words[1:])


def _kill_probe(cmd, sv):
    """The liveness probe, which sends no signal: `kill -0` and then only PIDs, as literal words that are no option,
    one double-quoted bare parameter, or one `$name` alone that the command sets once to digits
    (ServiceView.set_once: digits split into digits, never into `-s SIG`)."""
    rest = cmd.words[2:]
    if not rest or [w.value() if _plain_word(w) else None for w in cmd.words[:2]] != ["kill", "-0"] \
            or any((w.value() or w.text).startswith("-") for w in rest):
        return False
    return _plain_kill_args(rest) or (len(rest) == 1 and len(rest[0].parts) == 1
                                      and sv.set_once(rest[0], cmd.span[0], "[0-9]+"))


def _plain_script(script, sv):
    """True when every pipeline of the command is plain simple commands: a reader with static arguments,
    `kill -0|-l|-L`, an fdisk listing, dd onto an ordinary file or /dev/null|stdout|stderr|fd/N, a git read; a later
    pipe stage only a filter."""
    from lib.shell_parse import SimpleCommand
    for pipeline, _sep in script.items:
        for i, stage in enumerate(pipeline.stages):
            if not isinstance(stage, SimpleCommand) or not _plain_simple(stage, sv, i > 0):
                return False
    return True


# The raw-text readings the rules had before OB-L11: `text` is the command, an interpreter's code or a runner's
# command line; `view` the command's executable view, or that code or line itself.
def _raw_daemon_json(text):
    return grep(r"(>|>>|tee|cp|mv|sed|awk)\s.*/etc/docker/daemon\.json", text)


def _raw_compose(text):
    return grep(r"docker.compose\s+(down|restart|stop)", text)


def _raw_prune(text):
    return grep(r"docker\s+system\s+prune\s+-a", text)


def _raw_disk(view):
    return grep(r"^\s*(dd|mkfs|fdisk|shred)\b", view)


def _raw_killall(view, family):
    return grep(r"(killall|pkill)\s+.*(" + (re.escape(family) + "|" if family else "") + "claude|docker)", view)


def _raw_kill_signal(view):
    return grep(r"(^|[ \t;|&])(kill)[ \t]+-", view)


def _raw_kill_pid(view):
    return grep(r"(^|[;&|]\s*)kill\s+[0-9]", view)


def _raw_systemctl(text, env):
    return grep(r"systemctl\s+" + DAEMON_VERBS + r"(\s+|\b)", text) \
        and not all_targets_whitelisted(text, r"systemctl\s+(stop|restart)", env["dev_systemd"], strip_service=True)


def _raw_workflow(text, view):
    return grep(r"(rm|mv)\s", view) and grep(WORKFLOW_STATE_RE, text)


# The command-position readings.
def _daemon_json_write(sv):
    """A redirection into daemon.json; tee, cp or mv naming it; dd with of= it; sed or awk editing it in place or naming
    it in code."""
    from lib.shell_parse import AWK_NAMES
    for site in sv.redirect_sites:
        if any(x.writes() and x.target is not None and DOCKER_DAEMON_JSON in x.target.text for x in site.cmd.redirects):
            return True
    for name, args, _s, _r in sv.sites:
        if name == "dd":
            for w in args:
                v = w.value()
                if v is None and DOCKER_DAEMON_JSON in w.text:
                    return True
                if v is not None and v.startswith("of=") and _abs_norm(v[3:], sv.cwd) == DOCKER_DAEMON_JSON:
                    return True
            continue
        if not any(DOCKER_DAEMON_JSON in w.text for w in args):
            continue
        if name in ("tee", "cp", "mv"):
            return True
        if name in ("sed", "gsed") + AWK_NAMES:
            vals = [w.value() for w in args]
            in_place = any(v is not None and (re.match(r"^-[A-Za-z]*i", v) or v.startswith("--in-place")
                                              or v in ("inplace", "--include=inplace")) for v in vals)
            in_code = any(DOCKER_DAEMON_JSON in w.text and w.value() != DOCKER_DAEMON_JSON for w in args)
            if in_place or in_code:
                return True
    return False


_COMPOSE_VALUE_OPTS = frozenset({"-f", "--file", "-p", "--project-name", "--profile", "--env-file",
                                 "--project-directory", "--ansi", "--parallel", "--progress"})


def _docker_compose_stop(sv):
    """The compose verb (the first non-option word after `compose`, past its global options' values) is down,
    restart or stop; a later argument (a service name, a command `exec` or `run` runs) is data."""
    for name, args, _s, _r in sv.named("docker", "docker-compose"):
        vals = [w.value() for w in args]
        if name == "docker":
            if "compose" not in vals:
                continue
            vals = vals[vals.index("compose") + 1:]
        k = 0
        while k < len(vals) and vals[k] is not None and vals[k].startswith("-") and vals[k] != "-":
            k += 2 if vals[k] in _COMPOSE_VALUE_OPTS else 1
        if k < len(vals) and vals[k] in ("down", "restart", "stop"):
            return True
    return False


def _docker_prune_all(sv):
    """`docker system prune` with -a/--all after `prune`."""
    for _n, args, _s, _r in sv.named("docker"):
        vals = [w.value() or "" for w in args]
        if "system" not in vals:
            continue
        i = vals.index("system")
        if vals[i + 1:i + 2] == ["prune"] and any(
                v.startswith("--all") or re.match(r"^-[A-Za-z]*a", v) for v in vals[i + 2:]):
            return True
    return False


def _dd_target_refused(path, sv):
    """True when dd writes a device other than /dev/null, zero, stdout, stderr or fd/*, another process's
    descriptor (/proc/<pid>/fd/N), or a path it cannot read."""
    if not path:
        return True
    if _dd_fd_of(_abs_norm(path) if path.startswith("/") else path) is not None:
        return False  # a descriptor: the command's own redirections are checked as dd's targets
    if locations.PROC_FD.match(_abs_norm(path, "/x")):
        return True  # /proc/<pid>/fd/N of a process other than this shell: its file cannot be read here
    if path.startswith("~"):
        path = os.path.expanduser(path)  # bash expands a tilde after of= too
        if path.startswith("~"):
            return True
    if not path.startswith("/"):
        if sv.named("cd", "pushd", "popd"):
            return True  # relative to a directory the command moves to
        path = os.path.join(sv.cwd, path)
    paths = [_abs_norm(path)]
    with contextlib.suppress(Exception):
        paths.append(_abs_norm(os.path.realpath(paths[0])))
    for p in paths:
        rel = locations.device_name(p)  # a file of the tmpfs mounted there (/dev/shm/x) is no device
        if rel is not None and not (rel in DD_DEV_OK or rel.startswith("fd/") or not locations.is_device(p)):
            return True
    return False


def _dd_fd_of(path):
    """The descriptor a path names (/dev/stdout, /dev/fd/N, /proc/self/fd/N ...), else None."""
    std = {"/dev/stdin": 0, "/dev/stdout": 1, "/dev/stderr": 2}
    if path in std:
        return std[path]
    m = re.match(r"^/(dev|proc/self|proc/thread-self)/fd/([0-9]+)$", path)
    return int(m.group(2)) if m else None




def _dd_redirect_targets(site, fds=(), extra=()):
    """Every file dd's simple command opens for writing, by any descriptor (N>, N>>, N<>, &>): of=/dev/fd/N,
    /proc/self/fd/N, /dev/stdout or /dev/stderr and a >&N duplication all write one of these. Linux reopens the
    file behind a descriptor an of= path names (`fds`), so a file opened on it for reading (3</dev/sda) is a
    target too, followed through N>&M and N<&M duplications. `extra`: a bare `exec`'s redirections in the command."""
    redirects = list(extra) + list(site.cmd.redirects)
    fds = set(fds)
    grew = True
    while grew:
        grew = False
        for x in redirects:
            if x.fd in fds and x.dup is not None and x.dup not in fds:
                fds.add(x.dup)
                grew = True

    def named(x):
        return bool(fds) and (x.fd in fds or (x.fd is None and x.fd_var is not None))
    return [x.target.value() for x in redirects
            if x.target is not None and x.dup is None and not x.close and x.op not in HEREDOC_OPS
            and (x.writes() or named(x))]


_DD_OPERANDS = ("if=", "of=", "bs=", "ibs=", "obs=", "cbs=", "count=", "skip=", "seek=", "iseek=", "oseek=",
                "conv=", "iflag=", "oflag=", "status=")
_FDISK_READS = ("-l", "--list", "-x", "--list-details", "-V", "--version", "-h", "--help")


def _destructive_disk(sv):
    """dd writing a device or an unreadable of=; any mkfs, mkfs.* or shred; fdisk other than a listing."""
    for name, args, site, _r in sv.sites:
        if name == "dd":
            fds = set()
            for w in args:
                v = w.value()
                lead = v if v is not None else w.text
                if lead.startswith("of="):
                    if _dd_target_refused(v[3:] if v is not None else None, sv):
                        return True
                    if v[3:].startswith("/") and _dd_fd_of(_abs_norm(v[3:])) is not None:
                        fds.add(_dd_fd_of(_abs_norm(v[3:])))
                elif v is None and not lead.startswith(_DD_OPERANDS):
                    return True  # a computed operand may be of=
            if any(_dd_target_refused(t, sv) for t in _dd_redirect_targets(site, fds, sv.exec_redirects)):
                return True
        elif name in ("mkfs", "shred") or name.startswith("mkfs."):
            return True
        elif name == "fdisk":
            if not any(v in _FDISK_READS or (v is not None and re.match(r"^-[A-Za-z]*l[A-Za-z]*$", v))
                       for v in (w.value() for w in args)):
                return True
    return False


def _kill_protected_family(sv, family):
    rx = re.compile("(" + (re.escape(family) + "|" if family else "") + "claude|docker)")
    return any(rx.search(w.value() if w.value() is not None else w.text)
               for _n, args, _s, _r in sv.named("killall", "pkill") for w in args)


def _kill_signal(sv):
    """kill with an option other than the exact -0 (probe), -l or -L (list): -09 is SIGKILL."""
    return any(v is not None and v.startswith("-") and v not in _KILL_PROBE_OPTS
               for _n, args, _s, _r in sv.named("kill") for v in (w.value() for w in args))


def _kill_pid(sv):
    return any(args and args[0].value() is not None and re.match(r"[0-9]", args[0].value())
               for _n, args, _s, _r in sv.named("kill"))


def _production_systemctl(sv, env):
    for _n, args, _s, _r in sv.named("systemctl"):
        vals = [w.value() for w in args]
        if vals and vals[0] in ("stop", "restart") and any(
                v is None or not v.startswith("-") and (v[:-8] if v.endswith(".service") else v)
                not in env["dev_systemd"].split() for v in vals[1:]):
            return True
    return False


def _workflow_state_removal(command, sv):
    """rm, mv, git rm or git mv naming a workflow state path; with computed operands, one the command names."""
    from lib.shell_parse import GIT_MV_RM, _git_from_resolved
    for name, args, site, r in sv.sites:
        if name == "git":
            # The subcommand as git reads it: past global options and their values (-C dir, -c k=v, --work-tree d).
            invs = _git_from_resolved(r, site.context)
            if not invs:
                continue
            sub, unresolved = invs[0].subcommand, invs[0].unresolved
            if sub not in GIT_MV_RM and not (sub is None and unresolved):
                continue
        elif name not in GIT_MV_RM:
            continue
        if any(re.search(WORKFLOW_STATE_RE, w.text) for w in args):
            return True
        elsewhere = any(w.value() in (None, "{}") for w in args) \
            or any(wr[0] == "xargs" for wr in r.wrappers) or "exec_argv" in site.context
        if elsewhere and grep(WORKFLOW_STATE_RE, command):
            return True
    return False


def service_rules(command, view, env, sv=None):
    """BS-20/21, BS-23, BS-25..BS-31: secrets, docker, disks, kills, units, workflow state (`view`: executable view).

    Read at command position through ServiceView (OB-L11); a command it cannot read keeps the raw-text reading."""
    sv = sv if sv is not None else ServiceView(command)
    family = env["family"]
    sensitive = sensitive_redirect(command)
    if sensitive == "write":
        refuse("BLOCKED: Attempting to write to sensitive file via Bash", f"Command: {command}",
               "Edit sensitive files manually — never via AI-driven Bash redirection.", released_line())
    elif sensitive == "redirect":
        refuse("BLOCKED: Attempting to redirect from/to sensitive file via Bash", f"Command: {command}",
               "Edit sensitive files manually — never via AI-driven Bash redirection.", released_line())

    # A rule refuses when its command-position reading refuses OR its pre-OB-L11 reading of the whole command
    # does, unless the command is a plain shape (_plain_script), for which the command-position reading is exact.
    def reads(raw_rule, structural):  # a raw-text rule: interpreter code and runner lines keep it
        if sv.raw:
            return raw_rule(command)
        return structural() or any(raw_rule(t) for t in sv.code + sv.runners) \
            or (not sv.plain and raw_rule(command))

    def reads_view(view_rule, structural, view=view):  # an executable-view rule: runner lines keep it
        if sv.raw:
            return view_rule(view)
        return structural() or any(view_rule(t) for t in sv.runners) or (not sv.plain and view_rule(view))

    if reads(_raw_daemon_json, lambda: _daemon_json_write(sv)):
        refuse("BLOCKED: Modifying Docker daemon config is refused", f"Command: {command}", released_line())
    if reads(_raw_compose, lambda: _docker_compose_stop(sv)):
        refuse("BLOCKED: docker-compose down/stop/restart is refused", f"Command: {command}", released_line())
    if reads(_raw_prune, lambda: _docker_prune_all(sv)):
        refuse("BLOCKED: docker system prune -a is refused", f"Command: {command}", released_line())
    if reads_view(_raw_disk, lambda: _destructive_disk(sv), sv.without(view, "dd", _dd_whole)):
        refuse("BLOCKED: Destructive disk operation detected", f"Command: {command}", released_line())
    if reads_view(lambda t: _raw_killall(t, family), lambda: _kill_protected_family(sv, family)):
        refuse(f"BLOCKED: Killing {family + '/' if family else ''}claude/docker processes is refused",
                   f"Command: {command}", released_line())
    if reads_view(_raw_kill_signal, lambda: _kill_signal(sv), sv.without(view, "kill", _kill_probe)):
        refuse("BLOCKED: kill with signals is refused — use graceful shutdown methods", f"Command: {command}",
                   released_line())
    prefix = env["prefix"]
    if (not prefix or not grep(re.escape(prefix), command)) \
            and reads(lambda t: _raw_systemctl(t, env), lambda: _production_systemctl(sv, env)):
        refuse("BLOCKED: systemctl stop/restart/disable/enable/reload/kill/try-restart/reload-or-restart is refused "
                   "for production services", f"Command: {command}",
                   f"Hint: only {env['dev_systemd']} is allowed{f' (and {prefix}-* takes the daemon-restart grant)' if prefix else ''}.",
                   released_line())
    if _raw_workflow(command, view) if sv.raw else (
            _workflow_state_removal(command, sv) or any(_raw_workflow(t, t) for t in sv.runners)
            or (not sv.plain and _raw_workflow(command, view))):
        refuse("BLOCKED: Deleting/moving workflow state files is refused", f"Command: {command}",
                   "These files are required by the workflow enforcement system.", released_line())


# ── Removal policy (BS-32, BS-33) ────────────────────────────────────────────

def let_through_unproven(entry, payload):
    """THE SEAM for the refusal record: the one place that learns an unproven command was let run.

    decide() calls it once per Bash call, and only when that call's verdict is ALLOW and removal_policy() could not
    prove the command safe (so not when a later rule of this hook refuses the call, and not under a /do or /allow
    release, which the removal policy never sees). `payload` is the parsed PreToolUse payload. `entry` is what
    removal_policy() returned:
        {"rule": "removal-policy", "kind": "let_through_unproven",
         "path": "primary" (the analyzer answered UNRESOLVED) or "degraded" (it gave no usable verdict),
         "reason": "UNRESOLVED <the analyzer's reason>" or "NO_VERDICT analyzer unavailable or gave no usable verdict"}
    Before the command runs, a snapshot of the repository at the payload's cwd is taken and named in the entry
    (entry["snapshot"], see snapshot_before()), so what the command removes or overwrites there can be brought back
    (the owner, 2026-10-04: discard, but recoverably). Then the entry goes to the refusal record (record(), kind
    "unproven") as one line: what was let through and why, then "snapshot: <ref> <commit>; bring a file back: ..."
    (and what it left out) or "snapshot: none, <why>".
    """
    shot = entry["snapshot"] = snapshot_before(payload)
    lines = [f"{entry.get('rule', 'removal-policy')} let through unproven: {entry.get('reason', '')}"]
    if "none" in shot:
        lines.append(f"snapshot: none, {shot['none']}")
    else:
        lines.append(f"snapshot: {shot['ref']} {shot['commit']}; bring a file back: {shot['restore']}")
        lines += [f"snapshot left out: {shot['left_out']}"] if shot.get("left_out") else []
    record("\n".join(lines), "unproven")


def snapshot_before(payload):
    """lib/checkpoint-core.sh write_checkpoint, run in the payload's cwd within CLAUDE_HOOK_SNAPSHOT_TIMEOUT (10 s:
    with the analyzer's 15 s it stays inside the CLI's 60 s for this hook, which settings.json leaves at its
    default), starting no push. A snapshot that is not taken never refuses: the reply says why. A repository whose
    snapshot ran past that limit gets none for CLAUDE_HOOK_SNAPSHOT_PAUSE (30 min) after it, so a repository too big
    to snapshot costs one wait per period, not one per command; its mark is a file in the hook state root, named by
    the repository's real top-level path. Returns {"ref", "commit", "restore"} (and "left_out" when files were left
    out) or {"none": why}."""
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
        return {"none": "the call names no working directory"}
    limit = duration(os.environ.get("CLAUDE_HOOK_SNAPSHOT_TIMEOUT", ""), "10s") or 10.0
    try:
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=limit).stdout.strip()
    except subprocess.TimeoutExpired:
        return {"none": f"the snapshot took longer than {limit:g} s (CLAUDE_HOOK_SNAPSHOT_TIMEOUT)"}
    except (OSError, subprocess.SubprocessError):
        top = ""
    if not top:
        return {"none": "not inside a git repository"}
    top = os.path.realpath(top)
    mark = os.path.join(state_dir(), ".checkpoint-overtime-" + hashlib.sha256(os.fsencode(top)).hexdigest()[:24])
    pause = duration(os.environ.get("CLAUDE_HOOK_SNAPSHOT_PAUSE", ""), "30m") or 1800.0
    with contextlib.suppress(OSError):
        since = os.stat(mark).st_mtime
        if 0 <= time.time() - since < pause:
            return {"none": "the last snapshot of this repository ran past its time limit at "
                    f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(since))}; the next is tried "
                    f"{pause:g} s after it (CLAUDE_HOOK_SNAPSHOT_PAUSE)"}
    script = ('. "$2" || exit 90; export CHECKPOINT_NO_PUSH=1; write_checkpoint "$1" "$3" "pre-command snapshot"; '
              'printf "%s\\n" "$?" "$checkpoint_commit" "$checkpoint_ref" "$checkpoint_left_out$checkpoint_notice"')
    try:
        p = subprocess.Popen(["bash", "-c", script, "snapshot", cwd, os.path.join(LIB, "checkpoint-core.sh"),
                              "an unproven Bash command let through (removal policy)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                             start_new_session=True)
    except OSError as exc:
        return {"none": f"the snapshot could not start: {exc}"}
    try:
        out = p.communicate(timeout=limit)[0]
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)  # git and all; its temp index is swept by a later snapshot
        p.wait()
        with contextlib.suppress(OSError), open(mark, "w", encoding="utf-8") as fh:
            fh.write(top + "\n")
        return {"none": f"the snapshot took longer than {limit:g} s (CLAUDE_HOOK_SNAPSHOT_TIMEOUT)"}
    rc, commit, ref, note = (out.split("\n", 3) + [""] * 4)[:4]
    note = note.strip()
    if rc == "0" and commit:
        shot = {"ref": ref, "commit": commit, "restore": f"git -C {top} restore --source={commit} -- <path>, or "
                f"git -C {top} show {commit}:<path from the repository's top>"}
        return {**shot, "left_out": note} if note else shot
    return {"none": {"0": "write_checkpoint wrote none (/harness off)", "2": "not inside a git repository",
                     "90": "the snapshot library could not be loaded"}.get(rc) or note
            or f"write_checkpoint failed (rc={rc or p.returncode}); see the checkpoint log"}


def _scratch_owner(payload):
    """The write policy's answers about the calling actor's own scratch directory: (owner test for a path, the note
    naming that directory or ""). Both are hooks/pretool-tool-policy.py's own (_scratch_status, _note_own_scratch),
    loaded as hooks/pretool-claude-config-guard.py loads that hook: the one definition of where an actor may write
    scratch files, with no second one here. An actor the write policy gives no directory (a main agent whose
    session scratch was not made, a subagent whose role does not resolve) owns nothing, and so does any failure
    to ask."""
    import importlib.util
    import io
    try:
        spec = importlib.util.spec_from_file_location("_tool_policy_scratch", os.path.join(HOOKS, "pretool-tool-policy.py"))
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        policy._bootstrap_security()
        role = policy.resolve_agent_type(payload)
        note = io.StringIO()
        with contextlib.redirect_stderr(note):  # the note for a refused write to system temp names the directory
            policy._note_own_scratch(role, payload, os.path.join(locations.DEFAULT_TEMP_DIR, "removal"))
    except BaseException:  # noqa: BLE001 - also a bootstrap that exits: nothing is owned
        return (lambda path: False), ""

    def owns(path):
        try:
            return policy._scratch_status(role, path, payload) == "owner"
        except Exception:  # noqa: BLE001
            return False
    return owns, note.getvalue().strip()


def _removal_in_own_scratch(proof, payload, owns):
    """Whether every file a removal names (lib/bash_execution_boundary.py `removal_targets`) lies inside the caller's
    own scratch directory, from every directory the command may run it in (the call's cwd and each literal `cd`,
    as written and normalised). A file passes when the place it resolves to and the directory holding its entry
    both pass the write policy's owner test, so a link outside that directory pointing into it does not."""
    targets, dirs, cwd = proof.get("targets"), proof.get("cwds"), payload.get("cwd")
    if not isinstance(targets, list) or not targets:
        return False
    for target in targets:
        if not isinstance(target, str) or not target:
            return False
        if os.path.isabs(target):
            paths = [target]
        elif not isinstance(dirs, list) or not isinstance(cwd, str) or not os.path.isabs(cwd):
            return False  # a relative name after a `cd` this reading cannot follow
        else:
            paths = [os.path.join(d, target) for d in [cwd] + dirs + [os.path.normpath(d) for d in dirs]]
        for path in paths:
            if not (owns(path) and owns(os.path.dirname(path.rstrip(os.sep)) or os.sep)):
                return False
    return True


def removal_policy(payload_text, command):
    """lib/bash_execution_boundary.py's verdict, then the owner's rule (2026-11-19) for what it cannot prove.

    The analyzer runs in its own process under a time and memory limit. A command it proves (PROVEN_INERT,
    PROVEN_SAFE_REMOVAL) passes; a filesystem removal it finds (FORBIDDEN_REMOVAL) is refused, unless the analyzer
    knows every file the command removes and each lies inside the calling actor's own scratch directory as the
    write policy defines it (the owner, 2026-11-19: one's own temp folder may be deleted). A command it cannot
    prove safe is judged on one of two paths, which are two rules, not one:
      primary  — the analyzer answers UNRESOLVED. It has already refused every removal it sees where it would be
                 executed (a removal program in command position, find -delete, git rm/clean, a removal call in
                 Python it reads with ast). What is left runs, unless the analyzer names residue: a computed
                 program or command text, or inline code in a language with no reader. Only there is the word list
                 (lib/pol_degraded_removal_reference.ere) asked, and only of the text that can become that command
                 (the analyzer's `unresolved_scopes`): never of a heredoc written to a file, another command's
                 arguments, a variable name or a message.
      degraded — the analyzer gives no usable verdict (timeout, memory ceiling, crash, bad JSON): nothing has been
                 read, so the word list is asked of the whole command text.

    Returns None for a proven command and, for an unproven one let run, the entry described at
    let_through_unproven().
    """
    analyzer = os.path.join(LIB, "bash_execution_boundary.py")
    decision, proof, scopes = "", None, None
    limit = duration(os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT", ""), "15s")
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
                    proof = v.get("removal_targets") if verdict == "FORBIDDEN_REMOVAL" else None
                    scopes = v.get("unresolved_scopes") if verdict == "UNRESOLVED" else None
        except Exception:  # noqa: BLE001 - timeout, memory ceiling, crash, bad JSON: degraded mode
            decision, proof, scopes = "", None, None
    if decision == "ALLOW":
        return None
    unproven = not decision or decision.startswith("DENY UNRESOLVED ")
    named = True  # a removal the analyzer found is refused whatever the text holds
    if unproven:
        ere_file = os.path.join(LIB, "pol_degraded_removal_reference.ere")
        try:
            with open(ere_file, encoding="utf-8", errors="replace") as fh:
                rmref = next((ln.rstrip("\n") for ln in fh if not re.match(r"^\s*#", ln) and not re.match(r"^\s*$", ln)), "")
        except OSError:
            rmref = ""
        if not rmref:
            refuse(f"BLOCKED: removal-policy FAIL-CLOSED — the degraded removal-reference predicate at {ere_file} is "
                       f"missing or empty. Denied conservatively.", f"Command: {command}")
        primary = isinstance(scopes, list) and all(isinstance(t, str) for t in scopes)
        named = any(grep(rmref, t) for t in scopes) if decision and primary else grep(rmref, command)
    own = ()
    if named:
        try:
            payload = json.loads(payload_text)
        except ValueError:
            payload = None
        owns, note = _scratch_owner(payload if isinstance(payload, dict) else {})
        if isinstance(proof, dict) and isinstance(payload, dict) and _removal_in_own_scratch(proof, payload, owns):
            return None  # every file it removes is written out and lies in the caller's own scratch directory
        own = (note, "A removal runs when every file it names is written out in the command (no variable, pattern "
               "or `~`) and lies inside that directory.") if note else ()
    if decision and named:
        refuse(f"BLOCKED: removal-policy — {decision[5:]}", f"Command: {command}",
                   "REASON: every execution boundary must be provably inert or a provably non-filesystem removal (e.g. "
                   "git rm --cached, docker container rm) or a recoverable git rm (no -f, outside the harness home, no "
                   "submodule); this command has a boundary that is none of these."
                   + (" It could not be proven, and the text that can become a command it could not resolve holds a "
                      "removal word." if unproven else ""), released_line(), *own)
    if named:
        refuse("BLOCKED: removal-policy FAIL-CLOSED — the execution-boundary analyzer is unavailable or returned no "
                   "usable verdict, and this command's text holds a removal word. Denied conservatively.",
                   f"Command: {command}", f"REASON: repair the analyzer deployment at {analyzer}; an unproven command "
                   f"runs only when its text holds no removal word (lib/pol_degraded_removal_reference.ere).", *own)
    return {"rule": "removal-policy", "kind": "let_through_unproven", "path": "primary" if decision else "degraded",
            "reason": decision[5:] or "NO_VERDICT analyzer unavailable or gave no usable verdict"}


def kill_pid_rule(command, view, sv=None):
    """BS-35: kill <pid>, read at command position (OB-L11) and, unless the command is a plain shape, on the
    executable view as before; a command ServiceView cannot read keeps the view's reading alone."""
    sv = sv if sv is not None else ServiceView(command)
    if _raw_kill_pid(view) if sv.raw else (_kill_pid(sv) or any(_raw_kill_pid(t) for t in sv.runners)
                                           or (not sv.plain and _raw_kill_pid(view))):
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
    (re.compile(r"^(%s)[\d.]*$" % "|".join(PYTHON_NAMES)), ("-c",), ("-W", "-X")),
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
        if a in OPTION_ENDS or not a.startswith("-"):
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
_SAFE_DEVICES = locations.TERMINAL_SINKS | {locations.FD_DIR + "1", locations.FD_DIR + "2"}
_SHAPE_GIT_SUBS = frozenset({"status", "show", "diff", "log", "restore", "add", "commit", "rev-parse", "ls-files",
                             "stash", "checkout", "clean", "blame", "shortlog", "describe", "branch", "switch",
                             "cat-file", "ls-tree", "merge-base", "reflog", "tag"})
_SHAPE_GIT_GLOBALS = GIT_INERT_FLAGS | {"-C"}
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
    from lib.shell_parse import RG_RUN_OPTS
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
    if name in _SHAPE_SEARCHERS and any(a.startswith(RG_RUN_OPTS + ("--pager",))
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
            if sep not in (None, "", ";", "&&", "||", "\n") or any(p not in PIPE_OPS for p in pipeline.pipes):
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


# The first words after `git stash` that save the working tree (and with -u/-a its untracked files) and reset it.
_STASH_SAVE_WORDS = ("push", "save", "create", "store", "-u", "--include-untracked", "-a", "--all")
_STASH_SAVE_ALT = "|".join(map(re.escape, _STASH_SAVE_WORDS))


def _stash_pushes(args):
    first = args[0] if args else None
    return first is not None and (first in _STASH_SAVE_WORDS or (
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


def _worktree_global_scan(command):
    """The GC_GOPT reading of `git <global options> <subcommand>`, as a single left-to-right token scan with no cap.

    From each git word the scan walks the option run: an option word (-P, --no-pager, --git-dir=x ...), a value-shaped
    word (k=v, a path, anything holding a GC_VMARK character), or the plain word after a value-taking option
    (-C x, -c k=v, --git-dir x ...). Every word reached is a possible subcommand, as each is for the GC_GOPT regex
    (`-C stash` reads both as an option alone before `stash` and as -C with its value); a stash/checkout/restore word
    reached is judged by the per-form patterns on the rest of its own command (up to and including the first
    separator). A git word inside a run already walked is not walked again, so each word is visited once: a long run
    of options holding `git` (-Pgit, a=bgit, -C git) costs linear time, and a long option run before the subcommand
    is read to its end, however long."""
    hit = {"push": False, "bare": False, "checkout": False, "restore": False}
    for line in lines_of(command):
        toks = [(m.start(), m.group()) for m in _WT_TOKEN_RE.finditer(line)]
        sep = [len(w) == 1 and w in _WT_SEPS for _o, w in toks]
        n = len(toks)
        seg_start, seg_end = [0] * n, [len(line)] * n  # token i's command: its first offset, and just past its separator
        for t in range(1, n):
            seg_start[t] = toks[t][0] if sep[t - 1] else seg_start[t - 1]
        for t in range(n - 1, -1, -1):
            seg_end[t] = toks[t][0] + 1 if sep[t] else seg_end[t + 1] if t + 1 < n else len(line)
        restore_marks = {}  # per command: the last --source/-s and the last wide `-- path` start offsets
        i = 0
        while i < n:
            if sep[i] or not _WT_GIT_WORD_RE.fullmatch(toks[i][1]):
                i += 1
                continue
            j, after_valopt = i + 1, False
            while j < n and not sep[j]:
                off, word = toks[j]
                m = _WT_SUB_RE.match(word)
                if m:
                    end = seg_end[j]
                    rest = line[off:end]
                    if m.group(1) == "stash":
                        hit["push"] = hit["push"] or bool(_WT_PUSH_RE.match(rest) or _WT_PUSH_FLAGS_RE.match(rest))
                        hit["bare"] = hit["bare"] or bool(_WT_BARE_RE.match(rest))
                    elif m.group(1) == "checkout":
                        hit["checkout"] = hit["checkout"] or bool(_WT_CHECKOUT_RE.match(rest))
                    else:
                        if end not in restore_marks:
                            text = line[seg_start[j]:end]
                            restore_marks[end] = tuple(
                                max((seg_start[j] + x.start() for x in rx.finditer(text)), default=-1)
                                for rx in (_WT_SOURCE_RE, _WT_WIDE_RE))
                        hit["restore"] = hit["restore"] or min(restore_marks[end]) >= off
                if word.startswith("-"):
                    after_valopt = word in _WT_VALOPTS
                elif after_valopt or _WT_VALUE_SHAPED_RE.search(word):
                    after_valopt = False
                else:
                    break
                j += 1
            i = j  # the next walk starts at the word this one stopped on, never inside the run it walked
    return hit


def _worktree_raw_fallback(command, globals_=False):
    """The pre-parser patterns, for a command lib/shell_parse.py cannot read (fail closed). With globals_ (the
    quote-neutralised pass over a payload the parser may not read), git global options and their values
    (-C x, -c k=v, --git-dir=..., --no-pager ...) may stand between git and the subcommand, per the GC_GOPT grammar,
    read by _worktree_global_scan in linear time with no cap on the option run."""
    if globals_:
        return _worktree_global_scan(command)
    g = r"git\s+"
    return {
        "push": grep(g + r"stash\s+(" + _STASH_SAVE_ALT + r")\b", command)
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
        any(a in GIT_RESTORE_SOURCE_OPTS or a.startswith(tuple(o + "=" for o in GIT_RESTORE_SOURCE_OPTS))
            for a in i["args"])
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


# The quote-neutralised worktree pass: a line splits into commands at the GC_SEP separators and into words at
# whitespace. A git word is `git` or a path ending in `/git` (GC_GIT once the quotes are neutralised).
_WT_TOKEN_RE = re.compile(r"[;&|()`]|[^\s;&|()`]+")
_WT_GIT_WORD_RE = re.compile(r"""([^\s;&|()`'"]*/)?git""")
_WT_VALOPTS = frozenset(["-C", "-c"] + ["--" + n for n in GC_VALOPT_NAMES.split("|")])
_WT_VALUE_SHAPED_RE = re.compile(rf"[{GC_VMARK}]")
_WT_SEPS = frozenset(";&|()`")
_WT_SUB_RE = re.compile(r"(stash|checkout|restore)\b")
_WT_PUSH_RE = re.compile(r"stash\s+(" + _STASH_SAVE_ALT + r")\b")
_WT_PUSH_FLAGS_RE = re.compile(r"stash\s+-[ua]+\b")
_WT_BARE_RE = re.compile(r"stash\s*($|[;&|])")
_WT_CHECKOUT_RE = re.compile(r"checkout\s+\S+\s+--\s+(\.|\*|[^ ]+/)\s*($|[;&|])")
_WT_SOURCE_RE = re.compile(r"(?=(%s))" % "|".join(o + r"\b" for o in GIT_RESTORE_SOURCE_OPTS))
_WT_WIDE_RE = re.compile(r"(?=(--\s+(\.|\*|[^ /]+/)\s*($|[;&|])))")


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


_ALLOW_VERDICTS = ("", "ALLOW")  # the runtime guard's verdicts that let the command run


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
    if verdict in _ALLOW_VERDICTS and not lift:
        base_verdict, base_fc = _git_clean_base(command, stripped, view)
        if base_fc or base_verdict not in _ALLOW_VERDICTS:
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
_SD_HEAD_DIRS = locations.BIN_DIRS
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
_SD_GIT_GLOBAL_FLAGS = GIT_INERT_FLAGS | {"-p", "--paginate"}
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
_SD_COMMIT_LONG_VALUES = git_facts.GIT_COMMIT_VALUE_OPTIONS
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
    from lib.shell_parse import GREP_PATTERN_LONG
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
                if name in GREP_PATTERN_LONG:
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
    k = git_plain_subcommand_index(args, _SD_GIT_GLOBAL_FLAGS)
    if k is None:
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
            if a in OPTION_ENDS or not a.startswith("-"):
                return allowed, stdin  # a pathspec follows: its words are not messages
            if a.startswith("--"):
                name, eq, val = a.partition("=")
                if name in _SD_COMMIT_LONG_VALUES:
                    value_at = j if eq else j + 1
                    value = val if eq else (rest[j + 1] if j + 1 < len(rest) else None)
                    if name == "--message":
                        allowed.add(base + value_at)
                    if name == "--file" and value in ("-",) + locations.STDIN_DEVICES:
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
                    if c == "F" and value in ("-",) + locations.STDIN_DEVICES:
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
    if res.name in GREP_NAMES:
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
_SD_FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
# Interpreters: (short options whose value is code, short options that take the next word, long options whose
# value is code).
_SD_CODE_OPTS = (
    (re.compile(r"(%s)[0-9.]*" % "|".join(PYTHON_NAMES)), "c", "mWXQ", set()),
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
            if res.name in DECLARATION_BUILTINS:
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
    from lib.shell_parse import TAR_NAMES
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
            if a in FIND_NAME_TESTS and _sd_pattern_hits(vals[k + 1]):
                return vals[k + 1]
            if a in ("-regex", "-iregex") and _sd_pattern_hits(vals[k + 1], regex=True):
                return vals[k + 1]
        return None
    if name == "rg":
        hits = [h for h in opt_values({"--glob", "--iglob"}, "g") if not h.startswith("!")]
    elif name in GREP_NAMES:
        hits = opt_values({"--include"})
    elif name == "rsync":
        hits = opt_values({"--include"})
        for r in opt_values({"--filter"}, "f"):
            m = re.match(r"(\+|include)[ ,_]\s*(.*)", r)
            if m:
                hits.append(m.group(2))
    elif name in TAR_NAMES:
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
    from lib.shell_parse import AWK_PROGFILE_OPTS, AWK_SOURCE_OPTS, AWK_VALUE_OPTS
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
            if nm in AWK_PROGFILE_OPTS or a.startswith("-f"):
                from_file = True
            if nm in AWK_SOURCE_OPTS:
                code.append(v if eq else (vals[k + 1] if k + 1 < len(vals) else ""))
                from_file = True
            if a in AWK_VALUE_OPTS:
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
            if a in OPTION_ENDS:
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
        both = r.op in BOTH_STREAMS_OPS or (r.op == ">&" and r.io is None and r.dup is None and not r.close)
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
        if dashdash or a == "-" or not a.startswith(OPTION_SIGNS) or (a.startswith("+") and not numeric):
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
                    inner = st.kind not in DEFINER_KINDS
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
    if res.name in DECLARATION_BUILTINS + ("set", "env"):
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
    k = git_plain_subcommand_index(vals, _SD_GIT_GLOBAL_FLAGS)
    return None if k is None else vals[k]


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
_SD_PLAIN_GIT = frozenset({"status", "diff", "log", "show", "push", "fetch"})
# git options of those subcommands that run a program or write a file (taken in any abbreviation).
_SD_PLAIN_GIT_REFUSED = git_facts.GIT_RUN_OR_WRITE_OPTIONS
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
        if not r.writes() or r.target is None or r.target.value() != locations.NULL_DEVICE or \
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
    if name in COMMON_SHELLS:
        return len(vals) == 2 and vals[0] == "-c" and isinstance(res.payload, Script) and \
            _sd_plain_script(res.payload)
    if name == "find":
        actions = [v for v in vals if v in _SD_FIND_ACTIONS]
        return set(actions) <= {"-exec", "-execdir"} and len(actions) <= 1 and \
            (not actions or (isinstance(res.payload, Script) and _sd_plain_script(res.payload)))
    if res.payload is not None:
        return False
    if (name in _BULK_BENIGN and name != "printf") or name == "ls":  # printf: below
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
        if sep == "&" or any(p not in PIPE_OPS for p in pl.pipes):
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
    helper = os.environ.get("CLAUDE_DAEMON_RESTART_GRANT_HELPER", "")
    return {
        "prefix": os.environ.get("CLAUDE_PROTECTED_DAEMON_PREFIX", ""),
        "targets": os.environ.get("CLAUDE_PROTECTED_DAEMON_TARGETS", ""),
        "family": os.environ.get("CLAUDE_PROTECTED_PROCESS_FAMILY", ""),
        "dev_systemd": os.environ.get("CLAUDE_DEV_SYSTEMD", ""),
        "grant_dir": os.environ.get("CLAUDE_DAEMON_RESTART_SENTINEL_DIR")
                     or locations.DEFAULT_TEMP_DIR,  # the owner's helper's own rule
        "grant_hint": helper or "<daemon-restart grant helper>",
    }


def decide(payload_text):
    """The verdict token, or a refusal (refuse() exits 2)."""
    global PAYLOAD
    PAYLOAD = payload_text
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
    outward_rule(command)
    executable = executable_view_or_raw(command)
    sv = ServiceView(command, get("cwd"))
    service_rules(command, executable, env, sv)
    unproven = removal_policy(payload_text, command)
    kill_pid_rule(command, executable, sv)
    invs = git_view(command)
    shape = data_shape(command, invs)
    worktree_git_rules(command, invs, view, shape)
    git_clean_rule(command, executable, view, invs, shape)
    if unproven:
        let_through_unproven(unproven, payload)
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
