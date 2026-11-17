"""dispatch_scratch.py -- each dispatch's own scratch location, and the words a Bash
command names it by.

A subagent of a policy role has one scratch directory of its own:

    <project>/.claude/scratch/<session>/<role>/<agent_id>/

<session> is the provisioned resource session (lib/session_resources) when one
resolves, else the CLI session id; ``tmp/`` below it is the dispatch's TMPDIR.
hooks/subagentstart-record.py creates it and names it to the subagent at
dispatch; hooks/pretool-tool-policy.py judges a write into it as the owner's and
a write into another dispatch's as a sibling's.

A Bash write target is often a word the shell expands (``"$TMPDIR/out.txt"``,
``"$f"`` after ``f=$(mktemp)``). ``resolve_target`` gives the path such a word
names, from what the command itself assigns before it (a plain or ``export``
assignment at the top level of the command, assigned once) and the variables
the hook shares with the shell (its environment), or None when it cannot know.
A word bound to ``$(mktemp ...)`` resolves to mktemp's own template (its X's
kept), and is marked unique: mktemp creates a name no other process holds, so
two parallel dispatches cannot collide on it.

Pure: parses text and reads os.environ; writes nothing, except
``ensure_scratch``, which creates a dispatch's directory.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Mapping, NamedTuple, Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import shell_parse as _sp  # noqa: E402

_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REF = re.compile(r"\$\{([A-Za-z_]\w*)(?:(:?-)([^}$`]*))?\}|\$([A-Za-z_]\w*)")
# Commands that can (re)bind a shell variable without an assignment word.
_BINDERS = ("read", "for", "select", "declare", "typeset", "local", "readonly", "unset",
            "getopts", "mapfile", "readarray", "printf", "let")


def safe_id(value) -> bool:
    """A value usable as one path component of the scratch namespace."""
    return isinstance(value, str) and bool(_SAFE_ID.match(value)) and ".." not in value


def scratch_dir(project_dir, session_id: str, role: str, agent_id: str) -> Optional[str]:
    """The dispatch's own scratch directory (absolute), or None for an unsafe id."""
    if not (safe_id(session_id) and safe_id(role) and safe_id(agent_id)):
        return None
    session = session_id
    try:
        import session_resources

        pointer = session_resources.resolve_current_resource_session(project_dir, session_id)
        if safe_id(pointer.get("resource_session_id")):
            session = pointer["resource_session_id"]
    except Exception:  # no resource session provisioned: the CLI session names it
        pass
    return os.path.join(os.path.abspath(os.fspath(project_dir)), ".claude", "scratch", session, role, agent_id)


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def ensure_scratch(path: str, project_dir) -> bool:
    """Create the dispatch's directory and its tmp/; False when it cannot, or when the
    directory would not lie, symlinks resolved, at its own place below the project's
    .claude/scratch/ (a planted symlink on the way leads elsewhere)."""
    root = os.path.realpath(os.path.join(os.path.abspath(os.fspath(project_dir)), ".claude", "scratch"))
    rel = os.path.relpath(path, os.path.join(os.path.abspath(os.fspath(project_dir)), ".claude", "scratch"))
    expected = os.path.join(root, rel)
    if rel.startswith(os.pardir) or os.path.realpath(path) != expected or not _inside(expected, root):
        return False
    try:
        os.makedirs(os.path.join(path, "tmp"), exist_ok=True)
    except OSError:
        return False
    return os.path.realpath(os.path.join(path, "tmp")) == os.path.join(expected, "tmp")


class Value(NamedTuple):
    path: str
    unique: bool = False   # a name mktemp creates
    directory: bool = False  # mktemp -d


_UNKNOWN = object()


def _expand(text: str, scope: Mapping) -> Optional[str]:
    """``text`` with each $NAME / ${NAME} / ${NAME:-word} replaced, or None when a
    reference has no known value or any other expansion remains."""
    out, pos = [], 0
    for m in _REF.finditer(text):
        out.append(text[pos:m.start()])
        name = m.group(1) or m.group(4)
        value = scope.get(name, _UNKNOWN)
        if isinstance(value, Value):
            value = value.path
        if m.group(2) and (value is _UNKNOWN or value is None or (m.group(2) == ":-" and value == "")):
            value = m.group(3)
        if value is _UNKNOWN or value is None:
            return None
        out.append(value)
        pos = m.end()
    out.append(text[pos:])
    joined = "".join(out)
    return None if any(c in joined for c in "$`\x00") else joined


def _word_text(word, scope) -> Optional[str]:
    if word is None:
        return None
    static = word.value()
    if static is not None:
        return static
    if any(p.kind not in ("lit", "param") for p in word.parts):
        return None
    pieces = []
    for p in word.parts:
        pieces.append(p.text if p.kind == "lit" else "${" + p.text + "}")
    return _expand("".join(pieces), scope)


def _mktemp(word, scope, cwd: str) -> Optional[Value]:
    """The Value of a word that is exactly one $(mktemp ...) or `mktemp ...`."""
    parts = [p for p in word.parts if not (p.kind == "lit" and p.text == "")]
    if len(parts) != 1 or parts[0].kind not in ("cmdsub", "backtick") or parts[0].body is None:
        return None
    body = parts[0].body
    if body.error is not None or len(body.items) != 1 or len(body.items[0][0].stages) != 1:
        return None
    cmd = body.items[0][0].stages[0]
    if not isinstance(cmd, _sp.SimpleCommand) or cmd.assignments or cmd.redirects or not cmd.words:
        return None
    if cmd.words[0].value() != "mktemp":
        return None
    args = [_word_text(w, scope) for w in cmd.words[1:]]
    if any(a is None for a in args):
        return None
    directory = dry = tflag = False
    pdir, suffix, template = None, "", None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            template = args[i + 1] if i + 1 < len(args) else None
            break
        if a in ("--directory",):
            directory = True
        elif a in ("--dry-run",):
            dry = True
        elif a in ("--quiet",):
            pass
        elif a == "--tmpdir":
            pdir = pdir or ""
        elif a.startswith("--tmpdir="):
            pdir = a.split("=", 1)[1]
        elif a.startswith("--suffix="):
            suffix = a.split("=", 1)[1]
        elif a == "--suffix":
            i += 1
            suffix = args[i] if i < len(args) else ""
        elif a.startswith("--"):
            return None
        elif a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                c = a[j]
                if c == "d":
                    directory = True
                elif c == "u":
                    dry = True
                elif c == "q":
                    pass
                elif c == "t":
                    tflag = True
                elif c == "p":
                    rest = a[j + 1:]
                    if not rest:
                        i += 1
                        rest = args[i] if i < len(args) else None
                    if rest is None:
                        return None
                    pdir = rest
                    break
                else:
                    return None
                j += 1
        else:
            if template is not None:
                return None
            template = a
        i += 1
    env_tmp = scope.get("TMPDIR")
    if env_tmp is _UNKNOWN and (tflag or pdir == "" or (pdir is None and template is None)):
        return None  # the directory is $TMPDIR's, and its value or export is not known
    env_tmp = env_tmp.path if isinstance(env_tmp, Value) else env_tmp
    env_tmp = env_tmp if isinstance(env_tmp, str) and env_tmp else None
    # GNU mktemp: with -t, $TMPDIR, else -p DIR, else /tmp; without -t, -p DIR (or --tmpdir=DIR) wins,
    # else $TMPDIR, else /tmp, when a directory is in play (-p/--tmpdir given, or no template at all);
    # a template alone is taken from the current directory.
    if tflag:
        if template is not None and "/" in template:
            return None
        base = env_tmp or pdir or "/tmp"
    elif pdir is not None or template is None:
        base = pdir or env_tmp or "/tmp"
    else:
        base = cwd
    if template is None:
        template = "tmp.XXXXXXXXXX"
    if not re.search(r"X{3,}[^X/]*\Z", template):
        return None
    path = os.path.join(base, template + suffix)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return Value(os.path.normpath(path), unique=not dry, directory=directory)


def _assignment_value(a, scope, cwd) -> object:
    if a.array is not None or a.index is not None or a.append or a.value is None:
        return _UNKNOWN
    made = _mktemp(a.value, scope, cwd)
    if made is not None:
        return made
    text = _word_text(a.value, scope)
    return _UNKNOWN if text is None else text


def bindings(command: str, env: Mapping[str, str], cwd: str) -> dict:
    """Name -> str | Value | _UNKNOWN: the environment, overlaid with what the
    command's own top-level assignments bind. A name assigned anywhere else in
    the command (in a compound, a substitution, by read/for/declare/unset...),
    or more than once, or in a command that starts another shell, is unknown."""
    scope = dict(env)
    if not isinstance(command, str) or not command.strip():
        return scope
    script = _sp.parse(command)
    if script.errors():
        return scope
    top, conditional, exports = [], set(), []
    # Chains: the top-level items joined by && or ||. An assignment in a later element of a chain
    # runs only when the elements before it succeed (&&) or fail (||). Under a pure && chain every
    # later element runs only if it did, so it binds there; a use outside that chain (after ; or a
    # newline), any || chain and a backgrounded element (a subshell) leave the name unknown.
    chains, prev_sep = [], None
    for pl, sep in script.items:
        if prev_sep in ("&&", "||") and chains:
            chains[-1]["items"].append((pl, sep))
        else:
            chains.append({"items": [(pl, sep)]})
        prev_sep = sep
    for chain in chains:
        seps = [sep for _, sep in chain["items"][:-1]]
        chain["and_only"] = all(sep == "&&" for sep in seps)
        stages = [st for pl, _ in chain["items"] for st in pl.stages]
        chain["span"] = (stages[0].span[0], stages[-1].span[1]) if stages and all(
            getattr(st, "span", None) for st in stages) else None
    where = {id(pl): (chain, k) for chain in chains for k, (pl, _) in enumerate(chain["items"])}
    prev_sep = None
    for pl, sep in script.items:
        chain, k = where[id(pl)]
        maybe = sep == "&"
        if k > 0 and not maybe:
            maybe = not chain["and_only"] or chain["span"] is None
        prev_sep = sep
        if len(pl.stages) != 1 or not isinstance(pl.stages[0], _sp.SimpleCommand):
            continue
        cmd = pl.stages[0]
        found = []
        if not cmd.words:
            found.extend(cmd.assignments)
        elif cmd.words[0].value() == "export":
            words = cmd.words[1:]
            flagged = any((w.value() or "-").startswith("-") for w in words)
            for w in words:
                m = re.match(r"([A-Za-z_]\w*)(=?)", w.raw.text)
                if not m:
                    continue
                if flagged:  # export -n, -f, -p ...: what reaches a child is not modelled
                    conditional.add(m.group(1))
                elif m.group(2):
                    found.append(_sp.Assignment(w))
                    exports.append((w.span[0], m.group(1)))
                else:
                    exports.append((w.span[0], m.group(1)))
        if not maybe and k > 0:
            # a later element of a pure && chain: every use of the name must lie in this chain, after it
            span = chain["span"]
            for a in found:
                refs = [m.start() for m in re.finditer(r"\$\{?%s\b" % re.escape(a.name), command)]
                if any(not (a.word.span[1] <= r < span[1]) for r in refs):
                    conditional.add(a.name)
        if maybe:
            conditional.update(a.name for a in found)
        top.extend(found)
    counted, nested = {}, False
    for site in _sp.walk(script):
        # A target read from a shell the command starts (-c, a fed script, eval, an alias) does not
        # see the outer shell's unexported assignments: none is trusted then.
        nested = nested or any(c in ("shell_c", "heredoc_shell", "pipe_shell", "eval", "alias")
                               for c in site.context)
        cmd = site.cmd
        for a in getattr(cmd, "assignments", ()):
            counted[a.name] = counted.get(a.name, 0) + 1
        words = getattr(cmd, "words", ())
        if words and words[0].value() == "export":
            for w in words[1:]:
                m = re.match(r"([A-Za-z_]\w*)=", w.raw.text)
                if m:
                    counted[m.group(1)] = counted.get(m.group(1), 0) + 1
    if re.search(r"(?:^|[\s;&|(`])(?:source|\.|eval)\s", command):
        # a sourced or eval'd text can bind and export anything
        out = {name: _UNKNOWN for name in scope}
        out["TMPDIR"] = _UNKNOWN
        return out
    # Names a binder (read, declare, unset ...) or an unmodelled export touches: unknown in the
    # shell and to a child, before any assignment's value is computed.
    for m in re.finditer(r"(?:^|[\s;&|(`])(?:%s)\s+([^;&|\n]*)" % "|".join(map(re.escape, _BINDERS)), command):
        conditional.update(re.findall(r"[A-Za-z_]\w*", m.group(1)))
    names = {}
    for a in top:
        names[a.name] = names.get(a.name, 0) + 1
    for name in conditional:
        scope[name] = _UNKNOWN
    for name, n in counted.items():
        if nested or names.get(name) != n or n != 1 or name in conditional:
            scope[name] = _UNKNOWN
    for a in top:
        if scope.get(a.name) is _UNKNOWN:
            continue
        first_ref = re.search(r"\$\{?%s\b" % re.escape(a.name), command)
        if first_ref is not None and first_ref.start() < a.word.span[0]:
            scope[a.name] = _UNKNOWN
            continue
        # a child process (mktemp) sees a shell variable only once it is exported: an
        # assignment to a name the environment did not export, before an `export` of it,
        # stays in the shell
        exported = set(env) | {name for at, name in exports if at <= a.word.span[0]}
        scope[a.name] = _assignment_value(a, _child(scope, exported), cwd)
    scope[_EXPORTED] = frozenset(set(env) | {name for _, name in exports})
    return scope


_EXPORTED = "\0exported"  # bindings(): the names exported by the end of the command


def _child(scope: Mapping, exported) -> dict:
    """The variables a child process sees: the exported names' current values, and every
    name whose value or export is unknown (as unknown)."""
    return {name: value for name, value in scope.items()
            if name != _EXPORTED and (name in exported or value is _UNKNOWN)}


def _substituted_mktemp(target: str, scope, cwd: str) -> Optional[Value]:
    """A target that is one $(mktemp ...) word, or a mktemp -d one followed by /rest."""
    script = _sp.parse(": " + target)
    if script.errors() or len(script.items) != 1 or len(script.items[0][0].stages) != 1:
        return None
    cmd = script.items[0][0].stages[0]
    if not isinstance(cmd, _sp.SimpleCommand) or len(cmd.words) != 2:
        return None
    word = cmd.words[1]
    parts = [p for p in word.parts if not (p.kind == "lit" and p.text == "")]
    if not parts or parts[0].kind not in ("cmdsub", "backtick"):
        return None
    head = _sp.Word(word.segs, word.start, word.raw, (parts[0],))
    made = _mktemp(head, scope, cwd)
    if made is None:
        return None
    rest = "".join(p.text for p in parts[1:]) if all(p.kind == "lit" for p in parts[1:]) else None
    if rest is None:
        return None
    if not rest:
        return Value(made.path, unique=made.unique, directory=made.directory)
    if not rest.startswith("/") or "/.." in rest:
        return None
    return Value(os.path.normpath(made.path + rest), unique=made.unique and made.directory)


def resolve_target(target: str, command: str, env: Mapping[str, str], cwd: str) -> Optional[Value]:
    """The path a Bash write-target word names (absolute, normalized), or None
    when it cannot be known statically. ``unique`` is set when the word is a
    mktemp name, or lies below a mktemp -d directory."""
    if not isinstance(target, str) or not target or "\x00" in target:
        return None
    scope = bindings(command, env, cwd)
    if target.startswith(("$(", "`")):  # the parser put an assigned $(mktemp ...) in its variable's place
        return _substituted_mktemp(target, _child(scope, scope.get(_EXPORTED, ())), cwd)
    if "`" in target or "$(" in target:
        return None
    whole = re.fullmatch(r"\$\{?([A-Za-z_]\w*)\}?(/.*)?", target)
    unique = False
    if whole:
        bound = scope.get(whole.group(1))
        if isinstance(bound, Value) and bound.unique:
            unique = whole.group(2) is None or (bound.directory and "/.." not in whole.group(2))
    text = _expand(target, scope)
    if text is None:
        return None
    path = os.path.expanduser(text)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return Value(os.path.normpath(path), unique=unique)
