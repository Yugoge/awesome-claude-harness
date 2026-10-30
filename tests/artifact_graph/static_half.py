"""The static half of the artifact check (P1b E1, row 19).

`derive(tree)` reads one harness tree and returns every record the static
half derives, sorted:

* ``relation``: a read, write, create, unlink or rename of a path pattern at a
  literal code site (hooks/, scripts/ and the shell blocks of commands/*.md and
  agents/*.md), with the component, the mode, the API or command and file:line;
* ``unresolved``: a file operation whose path the static half could not
  resolve, with the reason (E1's miss classes);
* ``declaration``: obligation templates, canonical todo steps, the roster, the
  command files, schema ids and enums, hook registrations, gate switches;
* ``deciding``: a read followed by an exit, a block decision, a raise or a
  route on the read (E1's fallback rule), with the evidence;
* ``chain_call``: a call of the chain resolver and how its output is used;
* ``owner_output``: a path an owner-facing output shows (E12);
* ``rule7``: literals that may repeat a declaration, and tool-policy allow
  prefixes that name a file;
* ``declared_literal``, ``id_form``, ``id_regex``: sites holding a declared
  schema id or response marker, id-shaped templates and regexes matching a
  minted id (rule (2)'s reader candidates);
* ``raise_handler``: an except clause that turns an exception into a block;
* ``file``: each file in scope and how it was read;
* ``summary``: the counts.

Command line: ``python -m tests.artifact_graph <tree> <output.jsonl>`` writes
the records as sorted JSON lines; the output must lie outside the tree.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import declarations as D
from . import mdscan
from . import model as M
from . import patterns as P
from . import pyscan
from . import shparse as S
from . import shscan
from . import values as V

DEFAULT_CHAIN_SCRIPT = "scripts/resolve-dev-artifact-chain.py"   # row 7's one chain function

_EXCLUDED_DIRS = ("hooks/tests/", "scripts/install/tests/")


@dataclass
class StaticResult:
    records: list = field(default_factory=list)

    def by_kind(self, kind: str) -> list:
        return [r for r in self.records if r.get("kind") == kind]

    @property
    def relations(self) -> list:
        return self.by_kind("relation")

    @property
    def summary(self) -> dict:
        s = self.by_kind("summary")
        return s[0] if s else {}

    def jsonl(self) -> str:
        return "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                       for r in self.records)


def list_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".pytest_cache"))
        rel = os.path.relpath(dirpath, root)
        for fn in sorted(filenames):
            if fn.endswith((".pyc", ".pyo")):
                continue
            p = fn if rel == "." else f"{rel}/{fn}".replace(os.sep, "/")
            out.append(p)
    return sorted(out)


def _lang(root: Path, f: str) -> str:
    if f.endswith(".py"):
        return "python"
    if f.endswith((".sh", ".bash")):
        return "shell"
    base = f.rsplit("/", 1)[-1]
    if "." in base:
        return "other"
    try:
        with open(root / f, "rb") as fh:
            first = fh.readline(200)
    except OSError:
        return "other"
    if first.startswith(b"#!"):
        if re.search(rb"python", first):
            return "python"
        if re.search(rb"\b(ba)?sh\b|zsh|dash", first):
            return "shell"
    return "other"


def _in_scope(f: str) -> bool:
    if not (f.startswith("hooks/") or f.startswith("scripts/")):
        return False
    return not f.startswith(_EXCLUDED_DIRS)


def derive(tree, *, chain_script: str = DEFAULT_CHAIN_SCRIPT) -> StaticResult:
    """Derive the static half's records for the harness tree at `tree`."""
    root = Path(tree).resolve()
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 20000))
    try:
        return _derive(root, chain_script)
    finally:
        sys.setrecursionlimit(old_limit)
        pyscan.clear_caches()
        P.set_id_vocab({})


def _derive(root: Path, chain_script: str) -> StaticResult:
    files = list_files(root)
    file_set = set(files)

    def read_text(rel: str) -> str:
        return (root / rel).read_text(encoding="utf-8", errors="replace")

    findings = M.Findings()
    chain_base = chain_script.rsplit("/", 1)[-1] if chain_script else ""
    scope = [f for f in files if _in_scope(f)]
    langs = {f: _lang(root, f) for f in scope}
    py_files = [f for f in scope if langs[f] == "python"]
    sh_files = [f for f in scope if langs[f] == "shell"]
    py = pyscan.Analyzer(py_files, read_text, findings, chain_base)
    py.file_set = file_set
    py.id_samples = _id_samples(root, files)
    sh = shscan.ShellAnalyzer(py, findings, file_set, read_text, chain_base)

    for f in scope:
        if langs[f] == "other":
            findings.files.append((f, "other", "not-code", f.rsplit(".", 1)[-1] if "." in f.rsplit("/", 1)[-1] else ""))

    # The variables the command and agent blocks assign, and the id forms they mint.
    md_parsed, md_env = _markdown_envs(root, files, sh)
    vocab = _id_vocab(md_env)
    P.set_id_vocab(vocab)

    # Python modules: module level, then every function.
    for f in py_files:
        mod = py.module(f)
        if mod is None:
            findings.files.append((f, "python", "syntax-error", py.failed.get(f, "")))
            continue
        findings.files.append((f, "python", "parsed", ""))
    for f in py_files:
        mod = py.modules.get(f)
        if mod is None:
            continue
        pyscan.FunctionWalk(py, mod, None).run()
        for q in sorted(mod.funcs):
            py.summary(mod.funcs[q])
        pyscan.literal_facts(mod, findings)

    # Shell files: sources first, then the walk and every function.
    for f in sh_files:
        sf = sh.load(f)
        if sf is not None:
            _prescan_sources(sh, sf)
    for f in sh_files:
        sf = sh.files.get(f)
        if sf is None:
            continue
        sh.analyze_file(sf)
        for name in sorted(sf.funcs):
            sh.summary(sf, sf.funcs[name])

    # commands/*.md and agents/*.md shell blocks.
    _walk_markdown(md_parsed, md_env, sh, findings)

    # Declarations.
    decls: list[dict] = []
    obligations = _obligations(root, files, md_env)
    decls += obligations
    decls += D.todo_steps(root, files)
    roster = D.roster(root, files)
    decls += roster
    commands = D.command_files(root, files)
    decls += commands
    schema_decls = D.schemas(root, files)
    decls += schema_decls
    hook_regs, settings_env = _hook_registrations(root, files, sh, decls)
    decls += _gate_switches(py, sh, hook_regs, settings_env, findings)

    # Operations never bound at a call site are reported at their own site.
    for o in py.all_param_effects + sh.all_param_effects:
        if not py.instantiated.get(id(o)) and not sh.instantiated.get(id(o)):
            findings.ops.append(o)

    # Chain proxies (a function that returns the loaded resolver).
    _chain_proxies(py, findings)

    # A script's own arguments, bound to what each invocation passes.
    _bind_argv(findings, md_env)

    records: list[dict] = []
    rel_records, unresolved = _relations(findings, file_set, md_env)
    records += rel_records + unresolved
    records += decls
    records += _deciding(findings, md_env)
    records += [_chain_record(c) for c in findings.chain_calls]
    records += _owner_outputs(root, files, findings, sh, py, hook_regs)
    records += D.policy_prefixes(root, files)
    records += _literal_sites(root, py, sh, decls, obligations)
    records += _rule7(findings, roster, commands, schema_decls, obligations, read_text)
    records += [{"kind": "file", "file": f, "lang": lang, "status": st, "detail": det}
                for f, lang, st, det in findings.files]
    # handlers that turn an exception into a block (exit 2 or a block decision)
    records += [{"kind": "raise_handler", "component": comp, "site": f"{comp}:{line}", "catches": list(names)}
                for comp, line, names, blocks in findings.raise_handlers if blocks]
    records += [{"kind": "declaration", "type": "minted_id", "name": k, "form": P.shown_text(v)}
                for k, v in sorted(vocab.items())]
    records = _dedupe(records)
    records.append(_summary(records))
    records.sort(key=lambda r: json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return StaticResult(records)


def _dedupe(records: list) -> list:
    seen = set()
    out = []
    for r in records:
        k = json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _prescan_sources(sh: shscan.ShellAnalyzer, sf: shscan.ShFile) -> None:
    w = shscan.ShWalk(sh, sf, None)
    nodes = list(shscan.iter_nodes(sf.script.body))
    for fd in sf.funcs.values():
        nodes += list(shscan.iter_nodes([fd.body]))
    for n in nodes:
        if isinstance(n, S.Simple) and n.words and n.words[0].literal() in ("source", ".") and len(n.words) > 1:
            v = w.word(n.words[1], n)
            for t in V.as_templates(v):
                tgt = pyscan.tree_target(t, sh.file_set)
                if tgt and tgt not in sf.sourced and tgt != sf.component:
                    sf.sourced.append(tgt)
    sh.memo.clear()


# ---------------------------------------------------------------- markdown

def _markdown_envs(root: Path, files: list[str], sh: shscan.ShellAnalyzer) -> tuple[dict, dict]:
    """Parse the shell blocks of commands/*.md and agents/*.md; return the
    parsed blocks and, per file, the variables its blocks assign at top level
    (each block runs alone; the orchestrator carries values between them)."""
    md_files = sorted(f for f in files if re.match(r"^(commands|agents)/[^/]+\.md$", f))
    parsed_by: dict = {}
    envs: dict = {}
    for f in md_files:
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        parsed = []
        for b in mdscan.blocks(text):
            if b.info not in mdscan.SHELL_INFO:
                continue
            script = S.parse(mdscan.with_placeholders(b.text), b.start_line)
            parsed.append((b, script))
        env: dict = {}
        for _ in range(2):
            vals: dict = {}
            for b, script in parsed:
                sf = shscan.ShFile(f, script, origin="md-block", env=env)
                w = shscan.ShWalk(sh, sf, None)
                for n in script.body:
                    if isinstance(n, S.Simple) and n.assigns and not n.words:
                        for a in n.assigns:
                            if a[2] is not None:
                                vals.setdefault(a[0], []).append(w.word(a[2], n))
                    elif isinstance(n, S.Simple) and n.words and n.words[0].literal() == "export":
                        for wd in n.words[1:]:
                            a = S._assignment(wd)
                            if a and a[2] is not None:
                                vals.setdefault(a[0], []).append(w.word(a[2], n))
                sh.memo.clear()
            env = {k: _env_value(v) for k, v in sorted(vals.items())}
        envs[f] = env
        parsed_by[f] = parsed
    return parsed_by, envs


def _id_vocab(md_env: dict) -> dict:
    """Variables whose value the blocks mint from a run-time id and literal
    text only (``DEV_SESSION_ID="dev-$(date +%Y%m%d-%H%M%S)"``)."""
    forms: dict = {}
    bad: set = set()
    for f in sorted(md_env):
        for name, v in md_env[f].items():
            if isinstance(v, V.Unk):
                if v.hint in P.IDS:
                    forms.setdefault(name, set()).add(P.tok(v.hint))
                continue
            if not isinstance(v, V.Str):
                bad.add(name)
                continue
            for t in v.alts:
                toks = P.tokens_in(t)
                if not toks or "/" in t or not all(x in P.IDS for x in toks):
                    bad.add(name)
                    continue
                forms.setdefault(name, set()).add(t)
    out = {}
    for name in sorted(forms):
        if name in bad or len(forms[name]) != 1:
            continue
        t = next(iter(forms[name]))
        if t == P.tok(P.classify_name(name) or "-"):
            continue
        out[name] = t
    return out


def _walk_markdown(parsed_by: dict, envs: dict, sh: shscan.ShellAnalyzer, findings: M.Findings) -> None:
    for f in sorted(parsed_by):
        env = envs.get(f, {})
        for b, script in parsed_by[f]:
            sf = shscan.ShFile(f, script, origin="md-block", env=env)
            sh.files[f"{f}#{b.start_line}"] = sf
            _prescan_sources(sh, sf)
            sh.analyze_file(sf)
            for name in sorted(sf.funcs):
                sh.summary(sf, sf.funcs[name])
            findings.files.append((f"{f}:{b.start_line}", "shell-block", "parsed" if not script.errors else "partial",
                                   ",".join(str(x) for x in script.errors[:20])))
        sh.memo.clear()


def _env_value(vals: list) -> V.Val:
    resolved = [v for v in vals if isinstance(v, V.Str) and not any("ph:" in t for t in v.alts)]
    if resolved:
        return V.union(resolved)
    return V.union(vals)


def _resolve_ph(template: str, env: dict) -> str:
    def sub(m):
        name = m.group(1)
        key = name.split(" ")[0].strip('"')
        v = env.get(key)
        if isinstance(v, V.Str) and len(v.alts) == 1 and "ph:" not in v.alts[0] and not P.has_params(v.alts[0]):
            return v.alts[0]
        return m.group(0)
    return re.sub(P.L + r"ph:([^" + P.R + r"]+)" + P.R, sub, template)


def _md_env_for(component: str, md_env: dict) -> dict:
    return md_env.get(component, {})


def _obligations(root: Path, files: list[str], md_env: dict) -> list[dict]:
    out = []
    for f in sorted(files):
        if not re.match(r"^commands/[^/]+\.md$", f):
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        env = md_env.get(f, {})
        for ob in mdscan.obligations(text):
            arts = []
            for a in ob.get("artifacts") or []:
                rec = {"kind": a.get("kind")}
                if isinstance(a.get("path"), str):
                    t = _resolve_ph(mdscan.with_placeholders(a["path"]), env)
                    pat, holes, status = P.to_pattern(t)
                    rec["path"] = pat
                    rec["template"] = a["path"]
                for key in ("schema", "terminal_line_regex", "begin_marker", "end_marker"):
                    if isinstance(a.get(key), str):
                        rec[key] = a[key]
                arts.append(rec)
            out.append({
                "kind": "declaration", "type": "obligation",
                "command": f.rsplit("/", 1)[-1][:-3],
                "role": ob.get("role"), "pipeline": ob.get("pipeline"),
                "profile": sorted(p for p in ob.get("profile") or [] if p),
                "artifacts": arts, "form": ob.get("form"),
                "site": f"{f}:{ob.get('line')}",
            })
    return out


# ------------------------------------------------------------- settings

def _hook_registrations(root: Path, files: list[str], sh: shscan.ShellAnalyzer, decls: list) -> tuple[list, dict]:
    if "settings.json" not in files:
        return [], {}
    text = (root / "settings.json").read_text(encoding="utf-8", errors="replace")
    regs, env = D.settings_hooks(root, text)
    out = []
    for r in regs:
        script = S.parse(r["command"], r["line"])
        sf = shscan.ShFile("settings.json", script)
        w = shscan.ShWalk(sh, sf, None)
        target = None
        for n in shscan.iter_nodes(script.body):
            if isinstance(n, S.Simple):
                for wd in n.words:
                    for t in V.as_templates(w.word(wd, n)):
                        tg = pyscan.tree_target(t, sh.file_set)
                        if tg and target is None:
                            target = tg
        rec = {"kind": "declaration", "type": "hook_registration", "event": r["event"],
               "matcher": r["matcher"], "component": target, "command": r["command"],
               "timeout": r["timeout"], "site": f"settings.json:{r['line']}"}
        decls.append(rec)
        out.append(rec)
    sh.memo.clear()
    return out, env


def _py_closure(py: pyscan.Analyzer, start: str) -> list[str]:
    """Tree modules a Python file imports, transitively (itself included)."""
    seen = []
    todo = [start]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.append(p)
        mod = py.modules.get(p)
        if mod is None:
            continue
        import ast
        for n in ast.walk(mod.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    t = py.resolve_import(a.name, mod.path)
                    if t:
                        todo.append(t)
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                for a in n.names:
                    t = py.resolve_import((base + "." if base else "") + a.name, mod.path, n.level or 0)
                    if not t and (base or n.level):
                        t = py.resolve_import(base, mod.path, n.level or 0)
                    if t:
                        todo.append(t)
    return sorted(seen)


def _shell_assigned(sh) -> dict:
    """Names each shell file assigns anywhere (not env switches)."""
    out: dict = {}
    for key, sf in sh.files.items():
        names = out.setdefault(sf.component, set())
        nodes = list(shscan.iter_nodes(sf.script.body))
        for fd in sf.funcs.values():
            nodes += list(shscan.iter_nodes([fd.body]))
        for n in nodes:
            if isinstance(n, S.Simple):
                names.update(a[0] for a in n.assigns)
                if n.words and n.words[0].literal() in ("local", "declare", "typeset", "export", "readonly", "read"):
                    for w in n.words[1:]:
                        a = S._assignment(w)
                        if a:
                            names.add(a[0])
                        elif w.literal():
                            names.add(w.literal())
            elif isinstance(n, S.For):
                names.add(n.var)
    return out


def _gate_switches(py, sh, regs: list, settings_env: dict, findings: M.Findings) -> list[dict]:
    assigned = _shell_assigned(sh)
    by_comp: dict[str, list] = {}
    for e in findings.env_reads:
        by_comp.setdefault(e.component, []).append(e)
    switches: dict[str, dict] = {}
    for r in regs:
        comp = r.get("component")
        if not comp:
            continue
        comps = _py_closure(py, comp) if comp.endswith(".py") or comp in py.modules else [comp]
        sf = sh.files.get(comp)
        if sf is not None:
            comps = sorted(set(comps) | set(sf.sourced))
        for c in comps:
            for e in by_comp.get(c, []):
                name = e.name
                if not re.match(r"^[A-Z][A-Z0-9_]+$", name) or name in pyscan.ENV_ROOTS or P.classify_name(name) in P.IDS:
                    continue
                if not (name in settings_env or e.default is not None and e.default != "" or e.compared):
                    continue
                if name in assigned.get(e.component, ()):
                    continue
                sw = switches.setdefault(name, {"kind": "declaration", "type": "gate_switch", "name": name,
                                                "settings_value": settings_env.get(name), "readers": []})
                rd = {"hook": comp, "event": r["event"], "matcher": r["matcher"], "site": f"{e.component}:{e.line}",
                      "default": P.shown_text(e.default) if e.default is not None else None,
                      "compared": list(e.compared)}
                if rd not in sw["readers"]:
                    sw["readers"].append(rd)
    out = []
    for name in sorted(switches):
        sw = switches[name]
        sw["readers"].sort(key=lambda d: json.dumps(d, sort_keys=True))
        out.append(sw)
    return out


# ------------------------------------------------------------- relations

def _with_md(o: M.Op, md_env: dict) -> M.Op:
    if o.origin != "md-block":
        return o
    env = _md_env_for(o.component, md_env)
    path = V.map_str(o.path, lambda t: _resolve_ph(t, env)) if V.as_templates(o.path) else o.path
    src = V.map_str(o.src, lambda t: _resolve_ph(t, env)) if o.src is not None and V.as_templates(o.src) else o.src
    return M.Op(o.component, o.line, o.op, path, o.mode, o.via, o.lang, o.function, src, o.chain, o.origin, o.argv_from)


def _relations(findings: M.Findings, file_set: set, md_env: dict) -> tuple[list, list]:
    rels, unres = [], []
    for o in findings.ops:
        o = _with_md(o, md_env)
        recs = M.op_records(o, file_set)
        good = [r for r in recs if r["resolution"] != "unresolved"]
        if good:
            rels += good
            continue
        if recs:
            reasons = sorted({h for r in recs for h in r["holes"]}) or ["dynamic"]
            pat = recs[0]["path"]
        else:
            temps = V.as_templates(o.path)
            if temps:
                pat, holes, _ = P.to_pattern(temps[0])
                if P.is_os_path(pat):
                    continue
                reasons = list(holes) or ["dynamic"]
            else:
                pat = ""
                reasons = [V.reason_of(o.path)]
        unres.append({"kind": "unresolved", "component": o.component, "op": o.op, "mode": o.mode, "via": o.via,
                      "lang": o.lang, "site": f"{o.component}:{o.line}", "function": o.function,
                      "reason": _primary_reason(reasons), "reasons": reasons, "partial": pat,
                      **({"origin": o.origin} if o.origin else {}),
                      **({"through": list(o.chain)} if o.chain else {})})
    return rels, unres


_REASON_ORDER = ("data:payload", "data:record", "data:argv", "assembled:parameter", "assembled:listing",
                 "assembled:dict", "assembled:container", "assembled:stdout", "assembled:regex", "assembled:split",
                 "assembled:call", "assembled:loop", "assembled:unpack", "assembled:exception",
                 "assembled:recursive", "template:placeholder", "env", "glob", "varying", "dynamic")


def _primary_reason(reasons: list) -> str:
    def rank(r):
        base = r.split(":")[0] + ":" + r.split(":")[1] if r.count(":") >= 1 and not r.startswith("env") else r.split(":")[0]
        return (_REASON_ORDER.index(base) if base in _REASON_ORDER else len(_REASON_ORDER), r)
    return sorted(reasons, key=rank)[0]


_ARGV_RE = re.compile(re.escape(P.L) + r"argv:(\d+|--[A-Za-z0-9][\w-]*)" + re.escape(P.R))


def _bind_argv(findings: M.Findings, md_env: dict) -> None:
    """E1's argv class: an operation on a path a script takes as its N-th argument (sys.argv[N],
    $N) is that operation on each value an invocation of the script passes there, at the
    script's own site, the invocation's recorded beside it (`argv_from`)."""
    by_target: dict = {}
    for inv in findings.invocations:
        if inv.args:
            by_target.setdefault(inv.target, []).append(inv)
    bound = []
    for o in findings.ops + findings.deciding:
        invs = by_target.get(o.component)
        if not invs:
            continue
        path = o.path
        temps = V.as_templates(path)
        if not any(_ARGV_RE.search(t) for t in temps):
            continue
        for inv in sorted(invs, key=lambda i: (i.component, i.line)):
            env = _md_env_for(inv.component.split("#")[0], md_env)

            def arg(n) -> list:
                if isinstance(n, str):
                    # an option's value: the word after `--opt`, or the rest of `--opt=value`
                    words = [V.as_templates(a) for a in inv.args]
                    for i, alts_ in enumerate(words):
                        if n in alts_ and i + 1 < len(words):
                            return [_resolve_ph(x, env) for x in words[i + 1]]
                        eq = [x[len(n) + 1:] for x in alts_ if x.startswith(n + "=")]
                        if eq:
                            return [_resolve_ph(x, env) for x in eq]
                    return []
                if n > len(inv.args):
                    return []
                return [_resolve_ph(t, env) for t in V.as_templates(inv.args[n - 1])]

            alts = []
            for t in temps:
                cur = [t]
                for n in sorted({int(x) if x.isdigit() else x for x in _ARGV_RE.findall(t)}, key=str):
                    vals = arg(n)
                    if not vals:
                        cur = []
                        break
                    tok = P.argv(n) if isinstance(n, int) else P.tok("argv:" + n)
                    cur = [c.replace(tok, v) for c in cur for v in vals]
                alts += cur
            if not alts:
                continue
            via = f"{inv.component.split('#')[0]}:{inv.line}"
            if isinstance(o, M.Op):
                src = o.src
                bound.append(M.Op(o.component, o.line, o.op, V.make_str(alts), o.mode, o.via, o.lang, o.function,
                                  src, tuple(o.chain), o.origin, via))
            else:
                bound.append(M.Deciding(o.component, o.function, o.read_line, V.make_str(alts), o.read_mode,
                                        o.decision, o.evidence, o.lang))
    for b in bound:
        (findings.ops if isinstance(b, M.Op) else findings.deciding).append(b)


def _deciding(findings: M.Findings, md_env: dict) -> list[dict]:
    out = []
    for d in findings.deciding:
        temps = V.as_templates(d.path)
        env = _md_env_for(d.component, md_env)
        pats = []
        for t in temps:
            pat, holes, status = P.to_pattern(_resolve_ph(t, env))
            if not P.is_os_path(pat):
                pats.append((pat, status))
        if not pats:
            pats = [("<*>", "unresolved")]
        good = [p for p in pats if p[1] != "unresolved"] or pats[:1]
        for pat, status in sorted(set(good)):
            out.append({
                "kind": "deciding", "component": d.component, "function": d.function, "lang": d.lang,
                "path": pat, "resolution": status, "read_site": f"{d.component}:{d.read_line}",
                "read_mode": d.read_mode, "decision": d.decision.kind, "code": d.decision.code,
                "decision_site": f"{d.component}:{d.decision.line}", "detail": d.decision.detail,
                "through": list(d.decision.via), "evidence": d.evidence,
            })
    return out


def _chain_proxies(py: pyscan.Analyzer, findings: M.Findings) -> None:
    done = set()
    frontier = sorted(py.chain_proxies)
    depth = 0
    while frontier and depth < 4:
        depth += 1
        nxt = []
        for key in frontier:
            if key in done:
                continue
            done.add(key)
            for walker, call, stmt in py.calls_to.get(key, []):
                uses, fields = walker.chain_use_of(call)
                findings.chain_calls.append(M.ChainCall(walker.mod.path, walker.mod.ln(call), "proxy",
                                                        tuple(sorted(uses)), tuple(sorted(fields)), walker.fname,
                                                        f"{key[0]}:{key[1]}"))
                if "returned" in uses and walker.fi is not None:
                    nxt.append((walker.fi.module.path, walker.fi.qual))
        frontier = sorted(set(nxt))


def _chain_record(c: M.ChainCall) -> dict:
    return {"kind": "chain_call", "component": c.component, "site": f"{c.component}:{c.line}", "how": c.how,
            "uses": list(c.uses), "fields": list(c.fields), "function": c.function, "via": c.detail}


# ---------------------------------------------------------- owner outputs (E12)

def _owner_outputs(root: Path, files: list[str], findings: M.Findings, sh, py, regs: list) -> list[dict]:
    out = []
    registered = {r["component"] for r in regs if r.get("component")}
    # who relays whose systemMessage or stdout
    relayers: dict[str, set] = {}
    py_relayers = {rel[0] for rel in findings.system_message_relays if len(rel) == 2}
    for inv in findings.invocations:
        if inv.component in py_relayers:
            relayers.setdefault(inv.target, set()).add(inv.component)
    for comp, target in py.script_mentions:
        if comp in py_relayers and target != comp:
            relayers.setdefault(target, set()).add(comp)
    stdout_relays: dict[str, set] = {}
    for rel in findings.system_message_relays:
        if len(rel) == 3:
            stdout_relays.setdefault(rel[2], set()).add(rel[0])

    def reaches(comp: str) -> str:
        if comp in registered:
            return "registered"
        via = sorted(relayers.get(comp, ()))
        reg_via = [v for v in via if v in registered]
        if reg_via:
            return "relayed:" + reg_via[0]
        if via:
            return "relayed:" + via[0]
        return ""

    for o in findings.outputs:
        out.append({"kind": "owner_output", "channel": o.channel, "component": o.component,
                    "site": f"{o.component}:{o.line}", "shown": o.shown, "reaches": reaches(o.component)})
    # command text
    for f in sorted(files):
        if not re.match(r"^commands/[^/]+\.md$", f):
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        for line, shown, ev in mdscan.command_text_outputs(text):
            out.append({"kind": "owner_output", "channel": "command_text", "component": f,
                        "site": f"{f}:{line}", "shown": shown, "reaches": "command:" + ev})
    # prints of command blocks, of scripts commands run, of relayed stdout, of scripts run by hand
    by_hand = _run_by_hand(root, files, findings, sh, py, registered)
    invoked_by: dict[str, set] = {}
    printed_into: dict[str, set] = {}
    for inv in findings.invocations:
        if inv.component.startswith("commands/"):
            invoked_by.setdefault(inv.target, set()).add(inv.component)
        for t in inv.into:
            pat = P.to_pattern(t)[0]
            if pat.startswith(("<", "/")) and pat != "/dev/null":
                printed_into.setdefault(inv.target, set()).add((pat, inv.into_stderr))
    for comp, line, stream, shown, func, origin in sorted(py.prints + sh.prints):
        if origin == "md-block" and comp.startswith("commands/"):
            out.append({"kind": "owner_output", "channel": "command_print", "component": comp,
                        "site": f"{comp}:{line}", "shown": shown, "stream": stream, "reaches": "command:block"})
        if comp in invoked_by:
            out.append({"kind": "owner_output", "channel": "script_print", "component": comp,
                        "site": f"{comp}:{line}", "shown": shown, "stream": stream,
                        "reaches": "invoked_by:" + sorted(invoked_by[comp])[0]})
        if comp in stdout_relays and stream == "stdout":
            out.append({"kind": "owner_output", "channel": "system_message", "component": comp,
                        "site": f"{comp}:{line}", "shown": shown, "stream": stream,
                        "reaches": "relayed:" + sorted(stdout_relays[comp])[0]})
        if comp in by_hand and origin != "md-block":
            out.append({"kind": "owner_output", "channel": "hand_run_print", "component": comp,
                        "site": f"{comp}:{line}", "shown": shown, "stream": stream, "reaches": "by_hand"})
        for into, with_stderr in sorted(printed_into.get(comp, ())):
            # E12: a script's output its caller writes into a file reaches the owner where an
            # owner-facing output names that file (the landing's notice names its log); the
            # check decides that from the file's own readers
            if stream == "stdout" or with_stderr:
                out.append({"kind": "owner_output", "channel": "printed_into", "component": comp,
                            "site": f"{comp}:{line}", "shown": shown, "stream": stream,
                            "reaches": "into:" + into})
    return out


def _run_by_hand(root: Path, files: list[str], findings: M.Findings, sh, py, registered: set) -> set:
    """E12 for a script a person runs: what it prints reaches that person, the owner (a user-run
    entry point naming its log and pid file, as start-fswatch-all.sh does). A script is run by
    hand when its own text tells a person how to run it (a `Usage:` line naming the script) and
    nothing in the harness runs it: no hook registration, no invocation, source or import, and
    no line of a command or agent file, of settings.json or of another hook or script names it,
    other than a comment or a line that prints the name to a person ("Start with: bash
    .../start-fswatch-all.sh")."""
    import ast
    run = set(registered) | {inv.target for inv in findings.invocations}
    run |= {t for _, t in py.script_mentions}
    for sf in sh.files.values():
        run |= set(sf.sourced)
    for path in sorted(py.modules):
        for n in ast.walk(py.modules[path].tree):
            if isinstance(n, ast.Import):
                run |= {py.resolve_import(a.name, path) for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                run.add(py.resolve_import(n.module or "", path, n.level or 0))
                if n.module is None or n.level:
                    run |= {py.resolve_import(((n.module + ".") if n.module else "") + a.name, path,
                                              n.level or 0) for a in n.names}

    def text(f: str) -> str:
        try:
            return (root / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    cands = {}
    for f in files:
        if f in run or not f.startswith(("hooks/", "scripts/")) or f.endswith((".md", ".json", ".txt")):
            continue
        name = re.compile(r"(?<![\w.-])" + re.escape(f.rsplit("/", 1)[-1]) + r"(?![\w.-])")
        # the usage line, or the lines right under a bare `Usage:` heading
        if any(name.search(u.group(0)) for u in re.finditer(r"(?im)^\W*usage\b[^\n]*(?:\n[^\n]*){0,3}", text(f))):
            cands[f] = name
    if not cands:
        return set()
    # the harness text that runs things: command and agent files, settings.json, hooks and
    # scripts (their README and INDEX files describe, they run nothing)
    runners = [f for f in files if f == "settings.json"
               or f.startswith(("commands/", "agents/")) and f.endswith(".md")
               or f.startswith(("hooks/", "scripts/")) and not f.endswith(".md")]
    shown = re.compile(r"^\s*(?:#|echo\b|printf\b|print\(|>&2\s+echo\b)")
    out = set(cands)
    for f in runners:
        lines = text(f).split("\n")
        for c in sorted(out):
            if c == f:
                continue
            if any(cands[c].search(ln) and (f.endswith(".md") or f == "settings.json" or not shown.search(ln))
                   for ln in lines):
                out.discard(c)
    return out


# ------------------------------------------- rule (2): declared literals, ids

def _marker_literals(regex: str) -> list[str]:
    found = set(re.findall(r"[A-Z][A-Z0-9_]{2,}:", regex))
    found |= set(re.findall(r"[A-Z][A-Z0-9]*_[A-Z0-9_]{3,}", regex))
    return sorted(x for x in found if len(x) >= 5)


def _id_samples(root: Path, files: list[str]) -> list[str]:
    """Sample ids in the forms the command blocks mint (`date +FORMAT`)."""
    import time
    fixed = time.struct_time((2026, 1, 2, 3, 4, 5, 4, 2, 0))
    out = set()
    for f in sorted(files):
        if not re.match(r"^commands/[^/]+\.md$", f):
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        for fmt in re.findall(r"date (?:-u )?\+(%[^\s)\"'`]+)", text):
            sample = time.strftime(fmt, fixed)
            if re.search(r"\D", sample) and re.search(r"\d", sample):
                out.add(sample)
    return sorted(out)


def _literal_sites(root: Path, py, sh, decls: list, obligations: list) -> list[dict]:
    """Sites holding a declared schema id or response marker (rule (2)'s
    readers), regexes matching a minted id, and id-shaped templates."""
    import ast as _ast
    declared: dict[str, str] = {}
    for d in decls:
        if d.get("type") == "schema" and d.get("id"):
            declared[d["id"]] = "schema:" + d["site"]
    for ob in obligations:
        for a in ob.get("artifacts") or []:
            for key in ("begin_marker", "end_marker"):
                if a.get(key):
                    declared[a[key]] = "marker:" + ob["site"]
            if a.get("terminal_line_regex"):
                for lit in _marker_literals(a["terminal_line_regex"]):
                    declared.setdefault(lit, "terminal_line:" + ob["site"])
    import warnings
    samples = py.id_samples
    out = []

    def check(comp: str, line: int, text: str, lang: str) -> None:
        for lit, by in declared.items():
            # the marker as a whole word: CLOSE_REPORT inside CLOSE_REPORT_APPEND_ERROR or an
            # environment variable's name is another word, not the marker
            if lit in text and re.search(r"(?<![A-Za-z0-9_])" + re.escape(lit) + r"(?![A-Za-z0-9_])", text):
                out.append({"kind": "declared_literal", "component": comp, "site": f"{comp}:{line}",
                            "literal": lit, "declared_by": by, "lang": lang})
        if samples and len(text) < 300 and re.search(r"\\d|\[0-9\]", text):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    rx = re.compile(text)
            except re.error:
                rx = None
            hits = [m for m in (rx.search(s) for s in samples) if m] if rx is not None else []
            if any(m.end() - m.start() >= len(m.string) for m in hits):
                out.append({"kind": "id_regex", "component": comp, "site": f"{comp}:{line}", "regex": text,
                            "lang": lang})

    for key in sorted(py.modules):
        mod = py.modules[key]
        for n in _ast.walk(mod.tree):
            if isinstance(n, _ast.Constant) and isinstance(n.value, str) and id(n) not in mod.docstrings:
                check(mod.path, mod.ln(n), n.value, "python")
    for key in sorted(sh.files):
        sf = sh.files[key]
        nodes = list(shscan.iter_nodes(sf.script.body))
        for fd in sf.funcs.values():
            nodes += list(shscan.iter_nodes([fd.body]))
        for n in nodes:
            for w in shscan.node_words(n):
                for p in w.parts:
                    if isinstance(p, S.Lit) and p.text.strip():
                        check(sf.component, w.line, p.text, "shell")
    for comp, line, form, lang in py.id_forms + sh.id_forms:
        out.append({"kind": "id_form", "component": comp, "site": f"{comp}:{line}", "form": form, "lang": lang})
    return out


# ------------------------------------------------------------------ rule 7

def _declared_paths(obligations: list) -> list[tuple]:
    out = []
    for ob in obligations:
        for a in ob.get("artifacts") or []:
            if a.get("path"):
                out.append((a["path"], ob.get("role"), ob["site"], a.get("schema") or ""))
    return out


def _key_matches(key: str, declared: list) -> list:
    k = key.strip().strip("\"'")
    core = k.strip("*")
    if len(core.strip(".-_")) < 3 or re.fullmatch(r"\.[A-Za-z0-9]+", core):
        return []
    if "/" in core and not core.startswith(("docs/", ".claude/", "tests/")):
        return []
    hits = []
    for pat, role, site, schema in declared:
        base = pat.rsplit("/", 1)[-1]
        lit = re.sub(r"<[a-z*]+>", "", base)
        globbed = re.sub(r"<[a-z*]+>", "*", base)
        if core in lit or core in pat or _fnmatch(k, globbed):
            hits.append((pat, role, site, schema))
    return hits


def _fnmatch(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(pattern, name)


def _names_schema(text: str, schema: str) -> bool:
    """The code names the schema's documents: by the schema's id (qa-report.v2) or by the stem of
    that id (qa-report), the name of the artifact family the schema declares."""
    stem = re.sub(r"\.v\d+$", "", schema)
    return bool(re.search(r"(?<![\w-])" + re.escape(stem) + r"(?![\w])", text))


def _rule7(findings: M.Findings, roster: list, commands: list, schema_decls: list, obligations: list,
           read_text=None) -> list[dict]:
    names = {r["name"] for r in roster}
    cmds = {c["name"] for c in commands}
    enums = [(e["schema"], e["pointer"], e["site"], {v for v in e["values"] if isinstance(v, str)})
             for e in schema_decls if e["type"] == "schema_enum"]
    enums = [e for e in enums if len(e[3]) >= 2]
    props = {e["id"]: set(e.get("properties") or ()) for e in schema_decls if e["type"] == "schema"}
    declared = _declared_paths(obligations)
    texts: dict = {}

    def text_of(comp: str) -> str:
        f = comp.split("#", 1)[0]
        if f not in texts:
            try:
                texts[f] = read_text(f) if read_text else ""
            except OSError:
                texts[f] = ""
        return texts[f]
    out = []
    for lf in findings.literals:
        comp = lf.component
        if comp.startswith("scripts/todo/") or comp.startswith("agents/"):
            continue
        if not (comp.startswith(("hooks/", "scripts/", "commands/"))):
            continue
        site = f"{comp}:{lf.line}"
        elems = set(lf.elements)
        r = sorted(elems & names)
        if len(r) >= 2 and lf.shape in ("collection", "alternation", "mapping"):
            out.append({"kind": "rule7", "class": "roster_list", "component": comp, "site": site,
                        "shape": lf.shape, "names": r, "also_commands": sorted(elems & cmds)})
        for schema, ptr, esite, ev in enums:
            inter = elems & ev
            if len(inter) < 2:
                continue
            if ev <= elems:
                match = "equal" if ev == elems else "superset"
            elif elems <= ev:
                match = "subset"
            else:
                continue
            if read_text is not None and not _names_schema(text_of(comp), schema):
                # code that names neither the schema nor the artifact family it declares handles
                # none of its documents: its literal is a vocabulary of its own that shares words
                # with the enum (a status rank, a roster), not a copy of it
                continue
            out.append({"kind": "rule7", "class": "enum_copy", "component": comp, "site": site, "shape": lf.shape,
                        "schema": schema, "pointer": ptr, "enum_site": esite, "match": match,
                        "values": sorted(inter)})
        for k, v in lf.pairs:
            if v is None or v not in names or k is None:
                continue
            # a value the declared artifact's schema names as one of its properties is the field
            # the code reads in that document (the dev report's `dev` object), not a role
            hits = [h for h in _key_matches(k, declared) if v not in props.get(h[3], ())]
            if hits:
                out.append({"kind": "rule7", "class": "path_to_role", "component": comp, "site": site,
                            "shape": lf.shape, "key": k, "role": v,
                            "declared": sorted({h[0] for h in hits})[:6]})
    return out


# --------------------------------------------------------------- summary

def _summary(records: list) -> dict:
    def count(pred, key):
        out: dict = {}
        for r in records:
            if pred(r):
                k = key(r)
                out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))
    return {
        "kind": "summary",
        "relations_by_op": count(lambda r: r["kind"] == "relation", lambda r: r["op"]),
        "relations_by_resolution": count(lambda r: r["kind"] == "relation", lambda r: r["resolution"]),
        "relations_by_lang": count(lambda r: r["kind"] == "relation", lambda r: r.get("origin") or r["lang"]),
        "relation_sites": len({(r["site"], r["op"]) for r in records if r["kind"] == "relation"}),
        "distinct_paths": len({r["path"] for r in records if r["kind"] == "relation"}),
        "unresolved_by_reason": count(lambda r: r["kind"] == "unresolved", lambda r: r["reason"]),
        "unresolved_by_op": count(lambda r: r["kind"] == "unresolved", lambda r: r["op"]),
        "partial_holes": count(lambda r: r["kind"] == "relation" and r["resolution"] == "partial",
                               lambda r: ",".join(r["holes"])),
        "declarations": count(lambda r: r["kind"] == "declaration", lambda r: r["type"]),
        "deciding_by_decision": count(lambda r: r["kind"] == "deciding", lambda r: r["decision"]),
        "deciding_by_evidence": count(lambda r: r["kind"] == "deciding", lambda r: r["evidence"]),
        "deciding_reads": len({(r["read_site"], r["path"]) for r in records if r["kind"] == "deciding"
                               and r["evidence"] != "order" and r["decision"] != "route"}),
        "chain_calls_by_use": count(lambda r: r["kind"] == "chain_call", lambda r: ",".join(r["uses"])),
        "owner_outputs_by_channel": count(lambda r: r["kind"] == "owner_output", lambda r: r["channel"]),
        "rule7_by_class": count(lambda r: r["kind"] == "rule7", lambda r: r["class"]),
        "raise_handlers": sum(1 for r in records if r["kind"] == "raise_handler"),
        "files_by_status": count(lambda r: r["kind"] == "file", lambda r: r["lang"] + ":" + r["status"]),
    }


# ------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m tests.artifact_graph",
                                 description="Write the static half's records as sorted JSON lines.")
    ap.add_argument("tree", help="the harness tree to read")
    ap.add_argument("output", help="the JSON-lines file to write (outside the tree)")
    ap.add_argument("--chain-script", default=DEFAULT_CHAIN_SCRIPT)
    args = ap.parse_args(argv)
    tree = Path(args.tree).resolve()
    out = Path(args.output).resolve()
    if out == tree or tree in out.parents:
        sys.stderr.write(f"refusing to write inside the tree: {out}\n")
        return 2
    result = derive(tree, chain_script=args.chain_script)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.jsonl(), encoding="utf-8")
    s = result.summary
    sys.stdout.write(json.dumps(s, sort_keys=True) + "\n")
    return 0
