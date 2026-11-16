"""E1 differential: every fact an existing Bash reader extracts, the shared parser's view extracts.

For one command string, ``old_facts`` runs each reader the hooks use today and
``new_facts`` the matching view of hooks/lib/shell_parse.py. ``differences``
compares them and labels each difference with the reason it is allowed:

  * a reading the old reader gets wrong and the plan fixes (O4: a comment read
    as code; O6: quoted, option, heredoc or argument text read as code);
  * a fact the new view states another way (an undecidable target, a computed
    command word, an assignment projected into ``$X``, a path the caller
    derives from ``WriteTarget.source``);
  * a string bash itself rejects (``bash -n -c``, which runs nothing).

A difference with no label is unexplained, and the test that uses this module
fails on it.
"""

import collections
import functools
import importlib.util
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
LIB = os.path.join(HOOKS, "lib")
for path in (LIB, os.path.join(LIB, "runtime_guard")):
    if path not in sys.path:
        sys.path.insert(0, path)

import allowlist as AL  # noqa: E402
import bash_active_syntax_census as C  # noqa: E402
import bash_context_strip as CS  # noqa: E402
import bash_write_targets as WT  # noqa: E402
import git_command_classifier as GC  # noqa: E402
import shell_parse as sp  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SL = _load(os.path.join(LIB, "runtime_guard", "shell_lex.py"), "e1_runtime_shell_lex")
GG = _load(os.path.join(HOOKS, "pretool-grep-backtrack-guard.py"), "e1_grep_guard")
HS = _load(os.path.join(HOOKS, "pretool-harness-switch-guard.py"), "e1_switch_guard")

RESERVED = {"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "for", "select",
            "case", "esac", "in", "function", "{", "}", "[[", "]]", "!", "time", "coproc"}
WRITE_VERBS = set(sp.VERBS) | {"git rm", "git mv"}
GREPS = ("grep", "egrep", "fgrep", "ugrep")


def _safe(f):
    try:
        return f()
    except Exception as exc:  # a reader that raises has extracted nothing
        return "EXC:" + type(exc).__name__


def old_facts(c):
    f = {}
    f["strip"] = _safe(lambda: CS.strip_non_executable_contexts(c))
    f["wt_paths"] = _safe(lambda: WT.extract_bash_write_paths(c))
    f["wt_modes"] = _safe(lambda: [t.path for t in WT.extract_bash_write_targets_with_modes(c)])
    f["wt_touched"] = _safe(lambda: [p for p, _r in WT.extract_bash_touched_paths(c)])
    f["git"] = _safe(lambda: [[g.cmd_token, g.subcommand] for g in GC.iter_git_invocations(c)])
    f["grep"] = _safe(lambda: [x[0] if isinstance(x, (list, tuple)) else x for x in GG._find_searches(c)])
    f["settings"] = _safe(lambda: HS.writes_settings_file(c))
    f["allow_subs"] = _safe(lambda: AL._bash_subcommands(c))
    f["rg_redirs"] = _safe(lambda: [t for seg in SL._split_pipeline(c) for t in SL._write_redirect_targets(seg)])
    f["census_fatal"] = _safe(lambda: C.census(c)["fatal"])
    return f


def new_facts(c):
    s = sp.parse(c)
    sites = list(sp.walk(s))
    resolved = [sp.resolve(site.cmd) for site in sites]
    targets = sp.write_targets(s)
    grep_words = []
    for site, res in zip(sp.walk(s, into=("cmdsub", "backtick", "procsub", "heredoc_shell",
                                          "shell_c", "eval")), [None] * 10 ** 6):
        r = sp.resolve(site.cmd)
        if r.name in GREPS:
            for w in r.args:
                v = w.value()
                grep_words.append(w.text)
                if v:
                    grep_words.append(v)
                    if v.startswith("-") and "=" in v:
                        grep_words.append(v.split("=", 1)[1])
                    if v.startswith("-") and not v.startswith("--"):
                        grep_words.extend(v[k:] for k in range(2, len(v)))
    return {
        "error": s.error.code if s.error else None,
        "view": sp.executable_view(c),
        "targets": [t.path for t in targets if t.path],
        "resolved_targets": [WT._resolve_path(t.path) for t in targets if t.path],
        "undecidable": [(t.path, t.word.text if t.word is not None else "") for t in targets if not t.decidable],
        "dynamic": any(site.dynamic or site.templated for site in sites),
        "git": [[g.subcommand, g.unresolved] for g in sp.git_invocations(s, strings=True)],
        "grep": grep_words,
        "heads": [site.cmd.words[0].text for site in sites if site.cmd.words],
        "argv": [x for site in sites for x in site.cmd.argv() if x],
        "heredocs": [r.hd.body for site in sites for r in site.cmd.redirects if r.hd is not None],
        "redirs": [r.target.value() for site in sites for r in site.cmd.redirects
                   if r.target is not None and r.writes()]
        + [r.target.value() for pl, _ in s.items for st in pl.stages
           if isinstance(st, sp.Compound) for r in st.redirects if r.target is not None],
        "tree_words": _tree_words(s),
    }


def _tree_words(script):
    out = []
    for pl, _s in script.items:
        for st in pl.stages:
            if isinstance(st, sp.Compound):
                out.extend(w.literal() for w in st.header)
                out.append(st.name)
                for b in st.body:
                    out.extend(_tree_words(b))
                continue
            out.extend(a.word.literal() for a in st.assignments)
            out.extend(w.literal() for w in st.words)
            out.extend(r.target.literal() for r in st.redirects if r.target is not None)
            out.extend("{%s}" % r.fd_var for r in st.redirects if r.fd_var)
    return out


@functools.lru_cache(maxsize=None)
def bash_accepts(c):
    try:
        return subprocess.run(["bash", "-n", "-c", c], capture_output=True, timeout=10,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}).returncode == 0
    except (subprocess.TimeoutExpired, ValueError):
        return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _has_comment(c):
    return re.search(r"(^|[\s;&|()<>])#", c) is not None


def _data_strings(c):
    """Text bash reads as data: quoted argument text, non-shell heredoc bodies, option words."""
    out = []
    for site in sp.walk(sp.parse(c)):
        res = sp.resolve(site.cmd)
        for w in site.cmd.words[1:]:
            if w.text[:1] == "-":
                out.append(w.text)
            out.extend(p.text for p in w.parts if p.quote != sp.BARE and p.kind == "lit")
            if w.quoted():
                out.append(w.text)
        out.extend(a.word.text for a in site.cmd.assignments)
        for r in site.cmd.redirects:
            if r.hd is not None and not res.stdin_shell:
                out.append(r.hd.body)
            if r.target is not None and any(p.kind.startswith("procsub") for p in r.target.parts):
                out.append(r.target.text)
    return out


def _in_data(item, c):
    item = item.strip("'\"()\\ ")
    return bool(item) and any(item in d for d in _data_strings(c))


def _operand_site_names(item, c):
    names = []
    for site in sp.walk(sp.parse(c)):
        res = sp.resolve(site.cmd)
        vals = [(w.value() or w.text) for w in site.cmd.words]
        if any(item == v or item in v for v in vals[1:]):
            name = res.name
            if name == "git":
                g = sp.git_invocations(sp.parse(" ".join(w.text for w in site.cmd.words)))
                name = "git " + (g[0].subcommand or "") if g else name
            names.append(name)
    return names


def _copy_source(item, c):
    """``item`` is an operand of cp/mv/install/ln/rsync other than its last."""
    for site in sp.walk(sp.parse(c)):
        res = sp.resolve(site.cmd)
        if res.name in ("cp", "mv", "install", "ln", "rsync"):
            ops = [w.value() if w.value() is not None else w.text for w in res.args
                   if not (w.value() or "").startswith("-")]
            if item in ops[:-1]:
                return True
    return False


def _value_option_before(item, c):
    m = re.search(r"\s(-[\w-]+)\s+" + re.escape(item) + r"(\s|$)", c)
    return bool(m) and any(v[0] is not None and m.group(1) in v[0]["val"] for v in sp.VERBS.values())


def _is_resolved_head(item, c):
    for site in sp.walk(sp.parse(c)):
        head = sp.resolve(site.cmd).head
        if head is not None and head.value() == item:
            return True
    return False


def _label_items(reader, c, n, items):
    """The label of a difference whose lost items are ``items``, or None."""
    items = [str(x) for x in items]
    if _has_comment(c) and all(c.rfind(x) >= c.find("#") >= 0 for x in items if x in c):
        return "O4:old reads a comment as code"
    if all(x.isdigit() and re.search(re.escape(x) + r"[<>]", c) for x in items):
        return "O6:old reads a redirection's fd as an operand"
    if reader.startswith("wt_") and all(_value_option_before(x, c) for x in items):
        return "O6:old reads an option's value as an operand"
    if reader.startswith("wt_") and all(_is_resolved_head(x, c) for x in items):
        return "O6:old reads the command word as an operand (exec -a NAME)"
    if "$(" in c and all(c.rfind(x) > c.find(")", c.find("$(")) for x in items if x in c):
        return "O6:old reads past the end of a substitution"
    if all(any(ch in x for ch in "'\"\\") for x in items):
        return "O6:old reads quoting characters as part of an operand"
    if reader == "strip" and all(re.search(".{0,12}?".join(map(re.escape, x)), re.sub(r"\s+", " ", n["view"]))
                                 for x in items):
        return "covered:the new view keeps the whole word (old blanked a quoted piece of it)"
    if reader == "strip" and re.search(r"(python[\d.]*|node|ruby|perl|php)\s", c):
        return "O6:old keeps an interpreter's argv data where it misses the command word"
    if reader.startswith("wt_"):
        plain = [x for x in items if not any(ch in x for ch in "'\"\\")]
        sites = [_operand_site_names(x, c) for x in plain]
        if plain and all(s and not any(name in WRITE_VERBS for name in s) for s in sites):
            return "O6:old reads an argument word as the write verb"
        if re.search(r"(^|\s)(cp|mv|install)\s.*(-t|--target-directory)", c):
            return "O6:old reads a copy/move source as its destination (-t names it)"
        if re.search(r"git(\s+\S+)*?\s+rm\s.*--cached", c):
            return "O6:old misses `git rm --cached` behind a git global option"
    if reader.startswith("wt_") and all(_copy_source(x, c) for x in items):
        return "O6:old reads a copy/move source as a written target"
    if all(_in_data(x, c) or not x.strip("'\"()\\ ") for x in items):
        return "O6:old reads quoted/option/heredoc data as code"
    return None


def differences(c, m, n):
    """[(reader, label or None, detail)] for every fact of ``m`` that ``n`` does not hold."""
    out = []

    def add(reader, label, detail, items=()):
        if label is None and bash_accepts(c) is False:
            label = "bash-rejected"
        if label is None and items:
            label = _label_items(reader, c, n, items)
        out.append((reader, label, detail))

    # The census is an independent second reading: what it finds fatal, the parser rejects too.
    if isinstance(m["census_fatal"], list) and m["census_fatal"] and n["error"] is None:
        add("census", None, repr(m["census_fatal"]))
    if n["error"] is not None and n["error"] != "unterminated_heredoc" and bash_accepts(c):
        add("parse", None, n["error"])

    if isinstance(m["strip"], str):
        def toks(text):
            return collections.Counter(t for t in re.split(r"[\s'\"\\;&|(){}<>]+", text) if t)
        lost = toks(m["strip"]) - toks(n["view"]) - toks(re.sub(r"['\"]", "", n["view"]))
        if lost:
            label = None
            if n["error"] is None and _has_comment(c):
                label = "O4:the new view blanks a comment"
            elif "<<" in c:
                label = "view:heredoc data blanked"
            elif n["dynamic"]:
                label = "view:computed payload blanked"
            add("strip", label, repr(sorted(lost)[:6]), list(lost))

    newp = set(n["resolved_targets"])
    for key in ("wt_paths", "wt_modes", "wt_touched"):
        if isinstance(m[key], str):
            continue
        lost = {p for p in m[key] if p and p not in newp}
        if not lost:
            continue
        undecidable = n["undecidable"]
        if all(any(q.startswith(p.rstrip("`)")) for q in newp) for p in lost):
            label = "covered:the new path is the whole quoted word"
        elif undecidable and all(re.search(r"[$`*?\[]", p) or any(
                p == u[0] or p in u[1] or (u[0] and WT._resolve_path(u[0]) == p)
                or WT._resolve_path(os.path.expandvars(u[1].strip("'\""))) == p for u in undecidable)
                for p in lost):
            label = "covered:an undecidable target"
        elif all(any(q.startswith("~") and p.endswith(q[1:]) for q in n["targets"]) for p in lost):
            label = "covered:the same path under another HOME"
        elif re.search(r"\$\w+", c) and re.search(r"(^|[;&|\s])\w+=", c):
            label = "covered:assignment projected into $X"
        elif key == "wt_touched" and " mv " in " " + c and all(
                any(p.startswith(q.rstrip("/") + "/") for q in newp) for p in lost):
            label = "derived:<dest>/<basename(source)> from WriteTarget.source"
        else:
            label = None
        add(key, label, repr(sorted(lost)[:5]), sorted(lost))

    if isinstance(m["git"], list):
        def norm(x):
            return re.sub(r"['\"\\]", "", re.sub(r"\$'([^']*)'", r"\1", x or ""))
        subs = collections.Counter(norm(g[0]) for g in n["git"])
        unresolved = any(g[1] for g in n["git"])
        for tok, sub in m["git"]:
            s_ = norm(sub)
            if subs[s_] > 0:
                subs[s_] -= 1
                continue
            label = None
            if any((g[1] or "").startswith("invalid_global_option") for g in n["git"]):
                label = "git rejects an attached -c/-C (it runs nothing)"
            elif ("$" in s_ or s_ == "") and unresolved:
                label = "covered:an unresolved invocation"
            elif re.search(r"-C\s+" + re.escape(tok), c):
                label = "O6:old reads a wrapper option value as the command word"
            elif s_ and (_in_data(s_, c) or _in_data(tok, c) or s_.startswith("/")):
                label = "O6:old reads quoted/option/heredoc data as code"
            elif c.startswith("eval "):
                label = "old over-reads eval (bash joins the word values)"
            add("git", label, repr([tok, sub]))

    if isinstance(m["grep"], list):
        words = set(n["grep"])
        for p in m["grep"]:
            if p in words or any(p in w for w in words):
                continue
            add("grep", None, repr(p), [p])

    if m["settings"] is True:
        words = n["argv"] + n["heredocs"] + n["targets"]
        if not any(re.search(r"settings[\w.-]*\.json", x) for x in words):
            add("settings", None, "")

    if isinstance(m["allow_subs"], list):
        heads = {re.sub(r"['\"\\\n]", "", h) for h in n["heads"]}
        for sub in m["allow_subs"]:
            bare = re.sub(r"^(\d*[<>]+\s*\S+\s*)+", "", re.sub(r"^\(?[^()\s]*\)\s*", "", sub.strip()))
            bare = re.sub(r"^(\(\s*|\{\s+)+", "", bare)
            toks_ = bare.split()
            while toks_ and re.match(r"^[A-Za-z_]\w*=", toks_[0]):
                toks_ = toks_[1:]
            first = toks_[0].strip("'\"()") if toks_ else ""
            if not first or first in RESERVED:
                continue
            flat = re.sub(r"['\"\\\n]", "", bare)
            if any(flat.startswith(h) for h in heads if h) or any(
                    re.sub(r"['\"\\\n]", "", " ".join(toks_)).startswith(h) for h in heads if h):
                continue
            label = None
            if any(sub.strip() in b for b in n["heredocs"]) or first in re.findall(r"<<-?\s*['\"]?(\w+)", c):
                label = "old splits heredoc data lines (documented over-split)"
            elif "\\\n" in c:
                label = "covered:a line continuation"
            elif re.search(r"\bcase\b", c):
                label = "old splits a case pattern at |"
            elif "\\;" in c or ">|" in c or "|&" in c:
                label = "old splits at an escaped separator, `>|` or `|&`"
            elif "`" in c or "$(" in c:
                label = "old over-splits inside a substitution (documented)"
            elif n["dynamic"]:
                label = "covered:a computed command word (Site.dynamic)"
            add("allow_subs", label, repr(sub)[:100], [first])

    if isinstance(m["rg_redirs"], list):
        targets = {x for x in n["redirs"] if x}
        undecidable = any(x is None for x in n["redirs"])
        for t in m["rg_redirs"]:
            tn = t.strip("'\"()")
            if not t or tn in targets or tn.replace("'", "").replace('"', "") in targets or any(
                    x.startswith(tn) for x in targets):
                continue
            label = "covered:an undecidable target" if undecidable and re.search(r"[$`*]", t) else None
            add("rg_redirs", label, repr(t), [t])
    return out


def unexplained(c):
    """The differences of ``c`` that carry no label."""
    m, n = old_facts(c), new_facts(c)
    return [d for d in differences(c, m, n) if d[1] is None]
