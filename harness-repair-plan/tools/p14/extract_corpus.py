#!/usr/bin/env python3
"""Extract Bash command strings from the harness's test inputs into one JSON corpus.

Read-only over the repository: it parses files (ast / json), never imports or runs them.

Sources
  A. JSON fixtures (hooks/tests/fixtures, tests/fixtures, tests/differential, tests/replay):
     every string under a key named payload/command/cmd/raw/input (incl. tool_input.command).
  B. Python test files (hooks/tests, tests incl. tests/replay): string constants found
       strong: value of a dict key / keyword named command|cmd|payload|raw|cmd_input|CMD_INPUT,
               or the first positional argument of a call whose callee name looks like a
               command reader / hook runner (see READER_CALL_RE);
       weak:   an element of a list/tuple/set (module constants, parametrize rows) that
               also passes LOOKS_LIKE_COMMAND.
     Implicit concatenation and "a" + "b" are folded; f-strings are rendered with each
     placeholder replaced by the token PH (marked template=True).
Each record: {cmd, source, line, context, strength, template}.  Output is deduped on cmd.
"""
import ast
import json
import os
import re
import sys

REPO = os.environ.get("REPO", os.getcwd())
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus.json")

CMD_KEYS = {"command", "cmd", "payload", "raw", "cmd_input", "CMD_INPUT", "bash_command", "cmd_text",
            "command_text"}
READER_CALL_RE = re.compile(
    r"(analy[sz]e|census|^lex$|strip_non_executable|classify_git|iter_git_invocations|extract_bash|"
    r"command_without_heredoc|_find_searches|_segments|writes_settings|check_bash|^decide$|"
    r"run_hook|_run_hook|run_guard|_run_guard|_hook$|^hook$|_bash$|^bash$|bash_payload|_payload$|"
    r"make_payload|pretool|run_safety|_safety|_verdict|verdict$|_denied|_allowed|assert_den|assert_allow|"
    r"assert_block|assert_pass|_blocks?$|_passes$|_deny$|_allow$|_invoke|invoke$|_eb$|boundary|"
    r"_classify|classify$|_tokenize|tokenize|_shell_words|_command_token|_reduces_to|_lex$|"
    r"touched_paths|write_paths|write_targets|run_cmd|_run_cmd|runner|_case$|^case$|probe)",
    re.I)
LOOKS_LIKE_COMMAND = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"            # assignment prefix
    r"(?:[({!]\s*)?"                                      # subshell/group/negation
    r"(?:\\?[A-Za-z_./~][\w./+-]*|[\"'$`<>])"             # a command-word start
    r"[^\n]*?(?:\s|[;|&<>()$`])")                         # at least one more word / operator
PROSE = re.compile(r"^[A-Z][a-z]+(?: [a-z]+){4,}[.:]?$")  # an English sentence, not a command

records = {}


def add(cmd, source, line, context, strength, template=False):
    if not isinstance(cmd, str):
        return
    if not cmd.strip() or len(cmd) > 8000:
        return
    if strength == "weak" and (not LOOKS_LIKE_COMMAND.match(cmd) or PROSE.match(cmd)):
        return
    if cmd in records:
        r = records[cmd]
        r["hits"] += 1
        if r["strength"] == "weak" and strength == "strong":
            r.update(strength="strong", source=source, line=line, context=context)
        return
    records[cmd] = {"cmd": cmd, "source": source, "line": line, "context": context,
                    "strength": strength, "template": template, "hits": 1}


# ---------------------------------------------------------------- JSON fixtures
def walk_json(v, source, key=None):
    if isinstance(v, dict):
        for k, x in v.items():
            walk_json(x, source, k)
    elif isinstance(v, list):
        for x in v:
            walk_json(x, source, key)
    elif isinstance(v, str) and key in CMD_KEYS:
        add(v, source, 0, "json:" + key, "strong")


# ---------------------------------------------------------------- Python tests
def const_str(node):
    """(value, template) for a string-valued expression we can fold statically, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("PH")
        return "".join(parts), True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = const_str(node.left), const_str(node.right)
        if a and b:
            return a[0] + b[0], a[1] or b[1]
    return None


def callee_name(call):
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def docstring_nodes(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def scan_py(path):
    rel = os.path.relpath(path, REPO)
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return
    docs = docstring_nodes(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value in CMD_KEYS:
                    s = const_str(v)
                    if s:
                        add(s[0], rel, v.lineno, "dict:" + k.value, "strong", s[1])
        elif isinstance(n, ast.Call):
            name = callee_name(n)
            for kw in n.keywords:
                if kw.arg in CMD_KEYS:
                    s = const_str(kw.value)
                    if s:
                        add(s[0], rel, kw.value.lineno, "kw:" + kw.arg, "strong", s[1])
                if kw.arg == "env" and isinstance(kw.value, ast.Dict):
                    pass  # handled by the Dict branch
            if n.args and READER_CALL_RE.search(name or ""):
                s = const_str(n.args[0])
                if s:
                    add(s[0], rel, n.args[0].lineno, "call:" + name, "strong", s[1])
        elif isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            for e in n.elts:
                if id(e) in docs:
                    continue
                s = const_str(e)
                if s:
                    add(s[0], rel, e.lineno, "seq", "weak", s[1])
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and re.search(r"(?i)cmd|command|payload", n.targets[0].id):
            s = const_str(n.value)
            if s:
                add(s[0], rel, n.value.lineno, "assign:" + n.targets[0].id, "strong", s[1])


KEYWORDS = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac",
            "!", "{", "(", "time", "coproc", "function", "select", "[[", "[", "eval", "exec", "source", "."}
HEAD_RE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?\+?=(?:'[^']*'|\"[^\"]*\"|\S)*\s+)*"
                     r"[({!]*\s*([^\s;|&()<>]+)")


def head_of(cmd):
    m = HEAD_RE.match(cmd)
    if not m:
        return None
    return m.group(1).strip("\"'\\")


def refine_weak():
    """Keep a weak string only when its command word is one a strong string uses, a program on
    PATH, a shell keyword, a path, or a quoted/expanded (dynamic) head."""
    import shutil
    heads = {head_of(r["cmd"]) for r in records.values() if r["strength"] == "strong"}
    heads.discard(None)
    for cmd in list(records):
        r = records[cmd]
        if r["strength"] != "weak":
            continue
        h = head_of(cmd)
        base = (h or "").rsplit("/", 1)[-1]
        ok = bool(h) and h != "PH" and (
            base in heads or base in KEYWORDS or "/" in h or h[:1] in "$`" or cmd.lstrip()[:1] in "\"'$`"
            or (re.fullmatch(r"[\w.+-]+", base) and shutil.which(base)))
        if not ok:
            del records[cmd]


def main():
    roots = [os.path.join(REPO, "hooks", "tests"), os.path.join(REPO, "tests")]
    per_source = {}
    for root in roots:
        for d, _dirs, files in os.walk(root):
            if "__pycache__" in d:
                continue
            for f in sorted(files):
                p = os.path.join(d, f)
                before = len(records)
                if f.endswith(".py"):
                    scan_py(p)
                elif f.endswith(".json"):
                    try:
                        walk_json(json.load(open(p, encoding="utf-8")), os.path.relpath(p, REPO))
                    except (ValueError, UnicodeDecodeError):
                        pass
                got = len(records) - before
                if got:
                    per_source[os.path.relpath(p, REPO)] = got
    refine_weak()
    out = sorted(records.values(), key=lambda r: (r["source"], r["line"]))
    summary = {
        "total": len(out),
        "strong": sum(r["strength"] == "strong" for r in out),
        "weak": sum(r["strength"] == "weak" for r in out),
        "templates": sum(r["template"] for r in out),
        "multiline": sum("\n" in r["cmd"] for r in out),
        "files_contributing": len(per_source),
        "top_sources": sorted(per_source.items(), key=lambda kv: -kv[1])[:25],
    }
    json.dump({"summary": summary, "commands": out}, open(OUT, "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
