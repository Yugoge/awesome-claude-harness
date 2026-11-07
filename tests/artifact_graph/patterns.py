"""Path templates and the patterns both halves of the artifact check join on.

The static half evaluates path expressions into *templates*: plain text in which
run-time parts are written as tokens between the guillemets U+2039 and U+203A.
A token is one of

* a root: ``harness`` (the harness home), ``home`` (HOME), ``proj`` (the project
  directory a hook or a command runs in), ``state`` (the hook state directory of
  hooks/lib/harness_state_dir.py and .sh), ``tmpdir`` (TMPDIR / tempfile's root);
* a run-time id, as row 19 rule (1) names them: ``sid``, ``ts``, ``lane``, ``task``;
* ``*``, a part known to vary at run time (a glob, a nonce, a digest);
* ``rand``, the random part a temp-name generator mints (mktemp, tempfile): the
  runtime half writes the same part ``<rand>`` (tests/replay/trace.py);
* ``argv:N``, a script's N-th command-line argument (``sys.argv[N]``, ``$N``), bound
  to the values each invocation of the script passes (static_half);
* ``?<reason>``, a part the static half could not resolve, with the reason;
* ``@<name>``, a function parameter (only inside the analysis, never in output);
* ``ph:<name>``, a placeholder of a command or agent template (``<TASK_ID>``).

`to_pattern` turns a template into the output form, where every token is written
``<name>`` (``<*>`` for holes, parameters that name no id and unknown placeholders),
relative paths are rooted at ``<proj>``, ``~`` becomes ``<home>`` and ``<home>/.claude``
folds into ``<harness>`` (the harness home is ``$HOME/.claude`` in every install the
CLI loads; claude_home's env hint). The runtime half replaces concrete roots and ids
by the same tokens, so a static pattern is joined to a runtime one with `matches`:
``<task>`` and ``<*>`` match any id text, every other token matches only itself.
"""

from __future__ import annotations

import re
from typing import Iterable

L = "‹"
R = "›"

ROOTS = ("harness", "home", "proj", "state", "tmpdir")
IDS = ("sid", "ts", "lane", "task")

_TOKEN_RE = re.compile(L + r"([^" + L + R + r"]*)" + R)


def tok(name: str) -> str:
    return L + name + R


def argv(n: int) -> str:
    return tok("argv:%d" % n)


def hole(reason: str) -> str:
    return tok("?" + reason)


def param(name: str) -> str:
    return tok("@" + name)


def placeholder(name: str) -> str:
    return tok("ph:" + name)


WILD = tok("*")
RAND = tok("rand")


def tokens_in(template: str) -> list[str]:
    return _TOKEN_RE.findall(template)


def split(template: str) -> list[tuple[bool, str]]:
    """[(is_token, text)] in order."""
    out: list[tuple[bool, str]] = []
    pos = 0
    for m in _TOKEN_RE.finditer(template):
        if m.start() > pos:
            out.append((False, template[pos:m.start()]))
        out.append((True, m.group(1)))
        pos = m.end()
    if pos < len(template):
        out.append((False, template[pos:]))
    return out


def _param_hint(token: str) -> str:
    parts = token[1:].split("|")
    if any(not p.startswith(".") for p in parts[1:]):
        return ""
    keys = [p[1:] for p in parts[1:]]
    return keys[-1] if keys else parts[0]


def has_params(template: str) -> bool:
    return any(t.startswith("@") for t in tokens_in(template))


def literal_text(template: str) -> str:
    return "".join(text for is_tok, text in split(template) if not is_tok)


# ---------------------------------------------------------------- id classes

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _words(name: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(name or "")]


def classify_name(name: str) -> str | None:
    """The run-time id (or the project root) a variable, key or placeholder name
    stands for, from the words of the name; None when it names none of them.

    The words are the id kinds of row 19 rule (1) and their usual spellings.
    """
    words = _words(name)
    if not words:
        return None
    ws = set(words)
    if "lane" in ws or "lanes" in ws:
        return "lane"
    if "task" in ws or ("request" in ws and "id" in ws):
        return "task"
    if "dev" in ws and "session" in ws:
        # a dev session id names a task's registry (dev-<ts>, dev-command-<ts>,
        # or the overnight session's own id)
        return "task"
    if ws & {"timestamp", "ts", "stamp"}:
        return "ts"
    if "session" in ws or "sid" in ws:
        return "sid"
    if "project" in ws and ws & {"dir", "root", "path"}:
        return "proj"
    return None


# The ids the command files mint (`DEV_SESSION_ID="dev-$(date ...)"`), by
# normalized variable name; set for the length of one derivation.
_ID_VOCAB: dict[str, str] = {}


def _norm_name(name: str) -> str:
    return "_".join(_words(name))


def set_id_vocab(vocab: dict[str, str]) -> None:
    _ID_VOCAB.clear()
    for k, v in vocab.items():
        _ID_VOCAB[_norm_name(k)] = v


def id_template(name: str) -> str | None:
    """The template a variable name's value has: the command files' minted id
    form when one is known, else the bare id token of classify_name."""
    if not name:
        return None
    t = _ID_VOCAB.get(_norm_name(name))
    if t:
        return t
    kind = classify_name(name)
    return tok(kind) if kind else None


def _token_pattern(name: str) -> str | None:
    t = _ID_VOCAB.get(_norm_name(name))
    if t:
        return "".join("<" + x + ">" if is_tok else x for is_tok, x in split(t))
    kind = classify_name(name)
    return "<" + kind + ">" if kind else None


# ------------------------------------------------------------- normalization

_OS_PREFIXES = ("/dev/", "/proc/", "/sys/")


def is_os_path(pattern: str) -> bool:
    return pattern.startswith(_OS_PREFIXES) or pattern in ("/dev/null", "-")


def _norm_segments(path: str) -> str:
    lead = ""
    rest = path
    m = re.match(r"^(<[a-z]+>|/)", path)
    if m:
        lead = m.group(1)
        rest = path[len(lead):]
    segs: list[str] = []
    for seg in rest.split("/"):
        if seg in ("", "."):
            continue
        if seg == ".." and segs and segs[-1] not in ("..",) and not segs[-1].startswith("<*"):
            segs.pop()
            continue
        segs.append(seg)
    body = "/".join(segs)
    if lead == "/":
        return "/" + body
    if lead:
        return lead + ("/" + body if body else "")
    return body


def to_pattern(template: str, *, relative_root: str = "proj") -> tuple[str, tuple[str, ...], str]:
    """(pattern, hole reasons, status) of one template.

    status is ``full`` (no hole), ``partial`` (holes, but literal text beside the
    root) or ``unresolved`` (nothing literal beside the root).
    """
    holes: list[str] = []
    parts: list[str] = []
    for is_tok, text in split(template):
        if not is_tok:
            if "*" in text:
                pieces = text.split("*")
                for i, p in enumerate(pieces):
                    if i:
                        parts.append("<*>")
                        holes.append("glob")
                    parts.append(p)
            else:
                parts.append(text)
            continue
        if text in ROOTS or text in IDS:
            parts.append("<" + text + ">")
        elif text == "*":
            parts.append("<*>")
            holes.append("varying")
        elif text == "rand":
            parts.append("<rand>")
            holes.append("varying")
        elif text.startswith("argv:"):
            parts.append("<*>")
            holes.append("data:argv")
        elif text.startswith("?"):
            parts.append("<*>")
            holes.append(text[1:])
        elif text.startswith("@"):
            tp = _token_pattern(_param_hint(text))
            if tp:
                parts.append(tp)
            else:
                parts.append("<*>")
                holes.append("assembled:parameter")
        elif text.startswith("ph:"):
            tp = _token_pattern(text[3:].split(" ")[0])
            if tp:
                parts.append(tp)
            else:
                parts.append("<*>")
                holes.append("template:placeholder")
        else:
            parts.append("<*>")
            holes.append("dynamic")
    out = "".join(parts)
    out = re.sub(r"(?:<\*>)+", "<*>", out)
    if out.startswith("~/") or out == "~":
        out = "<home>" + out[1:]
    if not (out.startswith("/") or re.match(r"^<[a-z]+>", out) or out.startswith("<*>")):
        # a literal relative path is relative to the working directory; one that
        # starts with an unknown part may be absolute, so it keeps that part
        out = "<" + relative_root + ">/" + out
    out = _norm_segments(out)
    if out == "<home>/.claude" or out.startswith("<home>/.claude/"):
        out = "<harness>" + out[len("<home>/.claude"):]
    # a root names the start of a path; one inside a path (a slug or a key
    # built from a root's value) is not that root
    head = re.match(r"^<[a-z]+>", out)
    k = head.end() if head else 0
    rest = re.sub(r"<(?:%s)>" % "|".join(ROOTS), "<*>", out[k:])
    if rest != out[k:]:
        holes.append("assembled:root-embedded")
        out = out[:k] + rest
    lit = re.sub(r"<[a-z*]+>", "", out).replace("/", "").replace(".", "")
    if not lit and holes:
        status = "unresolved"
    elif holes:
        status = "partial"
    else:
        status = "full"
    return out, tuple(sorted(set(holes))), status


def pattern_root(pattern: str) -> str:
    m = re.match(r"^<([a-z]+)>", pattern)
    if m:
        return m.group(1)
    return "/" if pattern.startswith("/") else ""


# ------------------------------------------------------------------ joining

def pattern_regex(pattern: str) -> re.Pattern:
    out = []
    for m in re.finditer(r"<([a-z*]+)>|[^<]+|<", pattern):
        if m.group(1) is None:
            out.append(re.escape(m.group(0)))
        elif m.group(1) in ("*",):
            out.append(r".*?")
        elif m.group(1) in ("task", "rand"):
            out.append(r"(?:[^/]+?)")
        else:
            out.append(re.escape("<" + m.group(1) + ">"))
    return re.compile("^" + "".join(out) + "$")


def matches(static_pattern: str, runtime_pattern: str) -> bool:
    """True when a runtime pattern (concrete path with roots and ids tokenized)
    is an instance of a static pattern."""
    return bool(pattern_regex(static_pattern).match(runtime_pattern))


# --------------------------------------------------------- text path finder

PATH_IN_TEXT_RE = re.compile(
    r"(?:<[a-z*]+>|~|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\.{1,2}|[A-Za-z0-9_][A-Za-z0-9_.-]*)?"
    r"(?:/(?:<[a-z*]+>|[A-Za-z0-9_.*-])+)+"
)


def paths_in_text(text: str) -> list[str]:
    """Path-shaped substrings of shown text: at least one slash and a last
    segment with an extension or a token (``logs/checkpoint.log``)."""
    found: list[str] = []
    for m in PATH_IN_TEXT_RE.finditer(text):
        s = m.group(0).rstrip(".,;:")
        last = s.rsplit("/", 1)[-1]
        if not last:
            continue
        if "." in last.strip(".") or re.search(r"<[a-z*]+>", last):
            if s.startswith(("http:", "https:")):
                continue
            found.append(s)
    return found


def shown_text(template: str) -> str:
    """A template as the owner would see it: tokens written <name>."""
    parts = []
    for is_tok, text in split(template):
        if not is_tok:
            parts.append(text)
        elif text in ROOTS or text in IDS or text in ("*", "rand"):
            parts.append("<" + text + ">")
        elif text.startswith("@"):
            parts.append("<" + (classify_name(_param_hint(text)) or "*") + ">")
        elif text.startswith("ph:"):
            parts.append("<" + (classify_name(text[3:]) or "*") + ">")
        else:
            parts.append("<*>")
    return "".join(parts)


def uniq_sorted(items: Iterable) -> list:
    return sorted(set(items))
