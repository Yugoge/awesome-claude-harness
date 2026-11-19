#!/usr/bin/env python3
"""PreToolUse Hook (Bash): Block Bash write-bypass into views and cp-state.

Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass.

Blocks Bash commands that write (a redirect, or a writer such as tee, cp, mv, sed -i) a path
under a spec root -- a `.claude/specs/` or `docs/dev/specs/` directory, or the `specs/` of the
harness home wherever it is (lib/locations.spec_rest) -- that is one of:
  - a `*.lock.json` or `*manifest.json.lock` file anywhere under the root
  - `<root>/<id>/views/*.md` (views are read-only)
  - `<root>/<id>/views/manifest.json` (Write tool only)
  - `<root>/<id>/cp-state-*.json` (spec-check.py only)
A `touch` operand counts as a write, and a copy, move, install or link into a directory
(-t/--target-directory, a trailing `/`, several sources, or an existing directory) writes
`<dest>/<basename(source)>`.
A relative target is read from the call's directory and from every directory a `cd`/`pushd`
of the command names; each target is matched with `..` folded as text and by the real path of
its unfolded spelling (a symlink resolved before the `..` after it, as the kernel and `cd -P`
do), so `./`, `../`, absolute spellings, a symlink into a spec root and `link/../<id>/` are
refused alike. A lock file
or a views-shaped path outside every spec root (`/tmp/deps.lock.json`, a test fixture) passes.
Every `>`/`>>` in the raw text is read as a redirect target too (as the base guard read it),
so a command the shell parser cannot read is still checked.

Whitelist: a command that runs `.claude/scripts/spec-check.py` (or its quoted CLAUDE_HOME channel
spelling), by name or as python's first argument, is the legal writer: its own words and
redirections are not read (an --action text may hold `-> <view>`). Every other command of the
same line is read as it is alone; the script's name in a comment or an argument exempts nothing.

Fail-open on a payload that is not JSON. Exit 0 = allow, exit 2 = block.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import locations  # noqa: E402
from lib.sensitive_names import REDIRECT_OPS  # noqa: E402
try:
    from lib import shell_parse as _sp
    from lib.bash_write_targets import extract_bash_write_targets_with_modes as _write_targets
except Exception:  # the library is missing or broken: the textual scan below still runs
    _sp = None
    _write_targets = None

# Remediation paths are derived from THIS hook's own on-disk location
# (<harness-home>/hooks/<name>.py), so the message names the spec-check.py that
# actually exists for the invoking user instead of an author-absolute literal.
SPEC_CHECK = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"


# Matched against the part of a path below its spec root ("<id>/...").
BLOCK_PATTERNS = [
    re.compile(r"\.lock\.json"),
    re.compile(r"manifest\.json\.lock"),
    re.compile(r"^[^/]+/views/[^/]+\.md"),
    re.compile(r"^[^/]+/views/manifest\.json"),
    re.compile(r"^[^/]+/cp-state-[^/]+\.json"),
]

# A redirect target in raw text, for a command the parser cannot read.
_RAW_REDIRECT = re.compile(REDIRECT_OPS + r"\s*([^\s;&|<>()]+)")
_MAX_DIRS = 64

# The spellings of spec-check.py a command may run it by (_checker_spans)
WHITELIST_PATTERNS = [
    re.compile(r"\.claude/scripts/spec-check\.py"),
    re.compile(r'"\$\{CLAUDE_HOME:-\$HOME/\.claude\}/scripts/spec-check\.py"'),  # the quoted CLAUDE_HOME channel
    re.compile(r"bin/spec-check\.py"),  # legacy path; retained for compatibility with old invocations
]


def _load_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_command(data):
    if not isinstance(data, dict):
        return ""
    if data.get("tool_name") != "Bash":
        return ""
    tool_input = data.get("tool_input") or {}
    return tool_input.get("command") or ""


def _checker_spans(script):
    """(context, span) of each simple command that runs spec-check.py, the cp-state writer: the
    script is the command's own name or python's first argument (after flags that take no value,
    as -u or -B; -c and -m run something else), spelled as WHITELIST_PATTERNS."""
    out = []
    for site in _sp.walk(script):
        res = _sp.resolve(site.cmd)
        operand = [w for w in res.args if not re.fullmatch(r"-[bBdEIOqsSuvx]+", w.raw.text)][:1] \
            if re.fullmatch(r"python[\d.]*", res.name or "") else []
        for word in ([res.head] if res.head is not None else []) + operand:
            raw = word.raw.text
            if raw.rstrip("'\"").endswith("spec-check.py") and any(p.search(raw) for p in WHITELIST_PATTERNS):
                out.append((site.context, site.cmd.span))
                break
    return out


def _below_spec_root(path):
    """The text of ``path`` below its first spec root ("<id>/..."), or None."""
    return locations.spec_rest(path)


def _blocked_path(path):
    """The pattern a path written under a spec root hits, or None."""
    rest = _below_spec_root(path)
    if rest is None:
        return None
    for pattern in BLOCK_PATTERNS:
        if pattern.search(rest):
            return pattern.pattern
    return None


def _candidates(text, dirs):
    """Each absolute spelling of a written path: `..` folded as text, and the real path.

    The real path is taken of the UNFOLDED spelling, so a symlink is resolved before the `..`
    after it, as the kernel does (`link/../s1/x` with `link -> .claude/specs/s1`).
    """
    text = os.path.expanduser(text)
    bases = [""] if os.path.isabs(text) else dirs
    out = []
    for d in bases:
        joined = os.path.join(d, text)
        out.append(os.path.normpath(joined))
        try:
            out.append(os.path.realpath(joined))
        except (OSError, ValueError):
            pass
    out.append(text)  # as written: an unresolved expansion keeps the root it names
    return list(dict.fromkeys(out))


def _call_dir(data):
    cwd = data.get("cwd") if isinstance(data, dict) else None
    if isinstance(cwd, str) and os.path.isabs(cwd):
        return cwd
    return os.getcwd()


def _cd_dirs(script, call_dir):
    """The call's directory and each directory a `cd`/`pushd` names, read from those before it.

    A directory is kept unfolded (`<dir>/vlink/..`), so a target read from it is matched both as
    `cd` reads it by default (logical, `..` folded as text) and as `cd -P` does (the real path).
    """
    dirs = [call_dir]
    for site in _sp.walk(script):
        res = _sp.resolve(site.cmd)
        if res.name not in _sp.CD_TARGET_BUILTINS:
            continue
        args = [w.value() for w in res.args]
        args = [a for a in args if a is None or not (a.startswith("-") and a != "-")]
        if not args:
            new = [os.path.expanduser("~")]
        elif args[0] is None or args[0] == "-":
            continue  # computed, or back to a directory already listed
        else:
            target = os.path.expanduser(args[0])
            new = [target] if os.path.isabs(target) else [os.path.join(d, target) for d in dirs]
        for d in new:
            if d not in dirs and len(dirs) < _MAX_DIRS:
                dirs.append(d)
    return dirs


# Copy, move, install and link: into a directory destination the written path is
# `<dest>/<basename(source)>`.
_INTO_DIR = _sp.INTO_DIR_VERBS if _sp is not None else ()


def _word_text(w):
    v = w.value() if w is not None else None
    return os.path.expanduser(v) if v else None


def _into_dir_texts(script, dirs):
    """`<dest>/<basename(src)>` for each copy, move, install or link into a directory.

    The destination is a directory when it is named by -t/--target-directory, ends in `/`,
    follows several sources or already is a directory; `ln` with one operand links into `.`.
    """
    out = []
    for site in _sp.walk(script):
        res = _sp.resolve(site.cmd)
        if res.name not in _INTO_DIR or res.name not in _sp.VERBS:
            continue
        opts, operands, _err = _sp.split_options(list(res.args), _sp.VERBS[res.name][0], 0,
                                                  permute=True, lenient=True)
        names = {o for o, _v in opts}
        if names.intersection(_sp.NO_TARGET_DIR_OPTS):
            continue
        if res.name == "install" and names.intersection(_sp.INSTALL_DIR_OPTS):
            continue
        target_dir = [v for o, v in opts if o in _sp.TARGET_DIR_OPTS]
        if target_dir:
            dest, sources, into = _word_text(target_dir[-1]), operands, True
        elif res.name == "ln" and len(operands) == 1:
            dest, sources, into = ".", operands, True
        elif len(operands) >= 2:
            dest, sources = _word_text(operands[-1]), operands[:-1]
            into = bool(dest) and (dest.endswith("/") or len(sources) > 1 or any(
                os.path.isabs(c) and os.path.isdir(c) for c in _candidates(dest, dirs)))
        else:
            continue
        if not dest or not into:
            continue
        for s in sources:
            src = _word_text(s)
            base = os.path.basename(src.rstrip("/")) if src else ""
            if base and base not in (os.curdir, os.pardir):
                out.append(os.path.join(dest, base))
    return out


def _target_texts(command, checker=()):
    """The path text of every non-delete write target the parser finds, the checker's own aside."""
    out = []
    for t in _write_targets(command):
        if t.word is not None and any(c == t.context and a <= t.word.span[0] < b for c, (a, b) in checker):
            continue
        if t.path is not None:
            out.append(t.path)
        elif t.word is not None:
            out.append(t.word.raw.text.strip("'\""))
    return out


def _matches_block(command, call_dir):
    # Every `>` / `>>` in the raw text names a target, as the base guard read it (a quoted
    # `-> docs/dev/specs/<id>/views/x.md` included); the parser adds the targets of tee, cp,
    # mv, nested shells and the directories of `cd` chains.
    texts, checker = [], []
    dirs = [call_dir]
    if _sp is not None and _write_targets is not None:
        try:
            script = _sp.parse(command)
            spans = _checker_spans(script) if "spec-check.py" in command and script.error is None else []
            texts += _target_texts(command, spans)
            checker = spans  # the raw text is read around the checker only once the parser's targets are in
            dirs = _cd_dirs(script, call_dir)
        except Exception:
            pass
        try:
            texts += _into_dir_texts(script, dirs)
        except Exception:
            pass
    texts[:0] = [m.group(1).strip("'\"") for m in _RAW_REDIRECT.finditer(command)
                 if not any(a <= m.start(1) < b for _c, (a, b) in checker)]
    for text in dict.fromkeys(texts):
        if not text:
            continue
        for candidate in _candidates(text, dirs):
            hit = _blocked_path(candidate)
            if hit:
                return hit
    return None


def _emit_block(pattern, command):
    sys.stderr.write(
        "BLOCKED: Bash write-bypass into views/cp-state is forbidden\n"
        f"Pattern: {pattern}\n"
        f"Command: {command}\n"
        "Legal writers:\n"
        "  - views/*.md, manifest.json: Write tool (not Bash)\n"
        f"  - cp-state-*.json: python3 {SPEC_CHECK}\n"
        "Never `echo >` or `cat >` these paths.\n"
    )


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)
    command = _extract_command(data)
    if not command:
        sys.exit(0)
    hit = _matches_block(command, _call_dir(data))
    if hit:
        _emit_block(hit, command)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
