#!/usr/bin/env python3
"""Bounded executable-context view for pretool-bash-safety.sh.

This is deliberately NOT a full shell parser.  It only computes a conservative
view used by the generic danger-token rules in pretool-bash-safety.sh.

Safety invariants for live hook use:
- bounded input size; oversized input returns raw command (fail-closed)
- no unbounded recursion
- every scanner branch advances the index
- on any exception, return raw command unchanged
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MAX_COMMAND_CHARS = int(os.environ.get("CLAUDE_HOOK_CONTEXT_MAX_CHARS", "262144"))
_SHELL_INTERPS = {"bash", "sh", "zsh", "dash"}
_WRAPPER_PREFIXES = {"env", "time", "sudo", "nice", "ionice", "nohup", "timeout", "doas", "run0"}
# Options that consume one following argument when sudo is the wrapper.
_SUDO_OPTS_WITH_ARG = frozenset({"-u", "--user", "-g", "--group", "-C", "--close-from", "-D", "--chdir"})
# Commands whose arguments are the dangerous payload — do NOT strip their args.
DANGER_COMMANDS = frozenset({"killall", "pkill", "kill", "rm", "mv"})
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SCRIPT_INTERPS: frozenset[str] = frozenset({
    "python", "python3", "python2",
    "node", "nodejs",
    "ruby", "perl", "php", "lua",
    "rscript", "Rscript", "r", "R",
    "java", "kotlin", "scala", "groovy",
    "swift", "dotnet",
})


def _is_script_interp(name: str) -> bool:
    """Return True for versioned interpreter names like python3.12, node20."""
    base = re.split(r"[\d.]", name)[0]
    return base in _SCRIPT_INTERPS or name in _SCRIPT_INTERPS


def strip_non_executable_contexts(cmd: str) -> str:
    """Return a conservative executable-context view of *cmd*.

    Non-shell quoted string arguments are stripped so prompt/documentation text
    does not trigger kill/rm rules.  Shell executable contexts are preserved.
    """
    if not isinstance(cmd, str):
        return ""
    if len(cmd) > MAX_COMMAND_CHARS:
        return cmd
    try:
        return _process_compound(_process_heredocs(cmd))
    except Exception:
        return cmd


def _basename(word: str) -> str:
    return Path(word).name


def _consume_quoted(s: str, i: int) -> tuple[str, int]:
    quote = s[i]
    j = i + 1
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == "\\" and quote != "'":
            j = min(j + 2, n)
            continue
        if ch == quote:
            return s[i:j + 1], j + 1
        j += 1
    return s[i:n], n


def _consume_backtick(s: str, i: int) -> tuple[str, int]:
    return _consume_quoted(s, i)


def _consume_paren(s: str, i: int) -> tuple[str, int]:
    # i points at '('
    depth = 0
    j = i
    n = len(s)
    while j < n:
        ch = s[j]
        if ch in "'\"`":
            _, j = _consume_quoted(s, j)
            continue
        if ch == "(":
            depth += 1
            j += 1
            continue
        if ch == ")":
            depth -= 1
            j += 1
            if depth <= 0:
                return s[i:j], j
            continue
        j += 1
    return s[i:n], n


def _consume_dollar(s: str, i: int) -> tuple[str, int]:
    n = len(s)
    if i + 1 >= n:
        return "$", i + 1
    nxt = s[i + 1]
    if nxt == "(":
        span, end = _consume_paren(s, i + 1)
        return "$" + span, end
    if nxt == "{":
        j = i + 2
        depth = 1
        while j < n:
            ch = s[j]
            if ch in "'\"`":
                _, j = _consume_quoted(s, j)
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[i:j + 1], j + 1
            j += 1
        return s[i:n], n
    if nxt.isalpha() or nxt == "_":
        j = i + 2
        while j < n and (s[j].isalnum() or s[j] == "_"):
            j += 1
        return s[i:j], j
    # Positional/special shell params: $$, $?, $#, $1, etc.
    return s[i:i + 2], i + 2


def _split_top_level(cmd: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    current: list[str] = []
    sep = ""
    i = 0
    n = len(cmd)
    while i < n:
        start = i
        ch = cmd[i]
        if ch in "'\"":
            span, i = _consume_quoted(cmd, i)
            current.append(span)
        elif ch == "`":
            span, i = _consume_backtick(cmd, i)
            current.append(span)
        elif ch == "$":
            span, i = _consume_dollar(cmd, i)
            current.append(span)
        elif cmd.startswith("&&", i) or cmd.startswith("||", i):
            parts.append((sep, "".join(current)))
            sep = cmd[i:i + 2]
            current = []
            i += 2
        elif ch in ";|\n":
            parts.append((sep, "".join(current)))
            sep = ch
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1
        if i <= start:
            # Defensive invariant: scanners must always advance.
            current.append(cmd[start:start + 1])
            i = start + 1
    parts.append((sep, "".join(current)))
    return parts


def _tokenize_segment(segment: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(segment)
    while i < n:
        start = i
        ch = segment[i]
        if ch in " \t":
            j = i + 1
            while j < n and segment[j] in " \t":
                j += 1
            tokens.append((segment[i:j], "space"))
            i = j
        elif ch == "#":
            tokens.append((segment[i:], "comment"))
            i = n
        elif ch == "'":
            span, i = _consume_quoted(segment, i)
            tokens.append((span, "single"))
        elif ch == '"':
            span, i = _consume_quoted(segment, i)
            tokens.append((span, "double"))
        elif ch == "`":
            span, i = _consume_backtick(segment, i)
            tokens.append((span, "subst"))
        elif ch == "$":
            span, i = _consume_dollar(segment, i)
            tokens.append((span, "subst" if span.startswith("$(") else "word"))
        else:
            j = i + 1
            while j < n and segment[j] not in " \t'\"`#$;|&\n":
                j += 1
            tokens.append((segment[i:j], "word"))
            i = j
        if i <= start:
            tokens.append((segment[start:start + 1], "word"))
            i = start + 1
    return tokens


def _find_command_word(tokens: list[tuple[str, str]]) -> int | None:
    idx = 0
    while idx < len(tokens):
        text, kind = tokens[idx]
        if kind == "space":
            idx += 1
            continue
        if kind != "word":
            return idx
        word = text.strip()
        if not word:
            idx += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            idx += 1
            continue
        if word in _WRAPPER_PREFIXES:
            idx += 1
            # For sudo: consume its option-argument pairs before resuming.
            if word == "sudo":
                while idx < len(tokens):
                    t2, k2 = tokens[idx]
                    if k2 == "space":
                        idx += 1
                        continue
                    opt = t2.strip()
                    if opt == "--":
                        idx += 1  # consume "--" terminator, next token is cmd
                        break
                    if not (opt.startswith("-") or opt.startswith("+")):
                        break  # not an option; this is the command word
                    if opt in _SUDO_OPTS_WITH_ARG:
                        idx += 1  # consume the flag
                        # consume its value argument
                        while idx < len(tokens) and tokens[idx][1] == "space":
                            idx += 1
                        if idx < len(tokens):
                            idx += 1
                    else:
                        idx += 1  # no-arg flag (e.g. -H, -n, -S); skip flag only
            # env VAR=val cmd: skip assignments after env-like wrappers too.
            continue
        return idx
    return None


def _strip_double_content(text: str) -> str:
    inner = text[1:-1]
    out: list[str] = ['"']
    i = 0
    n = len(inner)
    while i < n:
        start = i
        if inner[i] == "$":
            span, i = _consume_dollar(inner, i)
            if span.startswith("$("):
                out.append(span)
        elif inner[i] == "`":
            span, i = _consume_backtick(inner, i)
            out.append(span)
        else:
            i += 1
        if i <= start:
            i = start + 1
    out.append('"')
    return "".join(out)


def _process_segment(segment: str) -> str:
    tokens = _tokenize_segment(segment.strip())
    if not tokens:
        return segment.strip()
    cmd_idx = _find_command_word(tokens)
    if cmd_idx is None:
        return "".join(t for t, _ in tokens)
    cmd_word = _basename(tokens[cmd_idx][0].strip())

    if cmd_word in _SHELL_INTERPS:
        return _process_shell_interp(tokens, cmd_idx)

    if _is_script_interp(cmd_word):
        return _process_script_interp(tokens, cmd_idx)

    # Danger commands' arguments ARE the dangerous payload — unquote them so that
    # hook patterns like (killall|pkill)\s+.*(happy|claude|docker) and kill[ \t]+-
    # match against the content (e.g. killall "happy" → killall happy, kill "-9" → kill -9).
    if cmd_word in DANGER_COMMANDS:
        out_d: list[str] = []
        for i, (text, kind) in enumerate(tokens):
            if i <= cmd_idx:
                out_d.append(text)
            elif kind in {"single", "double"} and len(text) >= 2:
                out_d.append(text[1:-1])  # strip surrounding quotes, expose content
            else:
                out_d.append(text)
        return "".join(out_d)

    out: list[str] = []
    for i, (text, kind) in enumerate(tokens):
        if i <= cmd_idx:
            out.append(text)
        elif kind == "single":
            out.append("")
        elif kind == "double":
            out.append(_strip_double_content(text))
        elif kind == "subst":
            out.append(text)
        elif kind == "comment":
            out.append("")
        else:
            out.append(text)
    return "".join(out)


def _process_shell_interp(tokens: list[tuple[str, str]], cmd_idx: int) -> str:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        text, kind = tokens[i]
        out.append(text)
        t = text.strip()
        if i > cmd_idx and kind == "word" and (t.startswith("-") or t.startswith("+")) and not t.startswith("--") and "c" in t[1:]:
            i += 1
            while i < len(tokens) and tokens[i][1] == "space":
                out.append(tokens[i][0])
                i += 1
            if i < len(tokens):
                payload, payload_kind = tokens[i]
                if payload_kind in {"single", "double"} and len(payload) >= 2:
                    # Expose shell code as executable text for grep rules.
                    out.append(" " + payload[1:-1])
                else:
                    out.append(payload)
                i += 1
            # Later args are positional args, not shell code; strip quoted text only.
            while i < len(tokens):
                later, later_kind = tokens[i]
                if later_kind in {"single", "double", "comment"}:
                    out.append("")
                else:
                    out.append(later)
                i += 1
            break
        i += 1
    return "".join(out)


_SHELL_METAS = frozenset("<>()`")


def _process_script_interp(tokens: list[tuple[str, str]], cmd_idx: int) -> str:
    """Strip argv tokens after a non-shell script interpreter.

    Word-kind tokens after cmd_idx that contain no shell metacharacters are
    pure argv data — strip them so they cannot trigger danger-token patterns.
    Tokens containing metacharacters (e.g. process substitution <(...)) are
    kept so genuine embedded shell execution remains detectable.
    """
    out: list[str] = []
    for i, (text, kind) in enumerate(tokens):
        if i <= cmd_idx:
            out.append(text)
        elif kind == "word" and not any(c in text for c in _SHELL_METAS):
            pass  # pure argv data; do not append
        elif kind == "single":
            out.append("")
        elif kind == "double":
            out.append(_strip_double_content(text))
        elif kind == "comment":
            out.append("")
        else:
            out.append(text)
    return "".join(out)


def _process_compound(cmd: str) -> str:
    return "".join(sep + _process_segment(seg) for sep, seg in _split_top_level(cmd))


def _first_word(text: str) -> str:
    toks = _tokenize_segment(text.strip())
    idx = _find_command_word(toks)
    if idx is None:
        return ""
    return _basename(toks[idx][0].strip())


def _process_heredocs(cmd: str) -> str:
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC_RE.search(line)
        if not m:
            out.append(line)
            i += 1
            continue
        delim = m.group(2)
        before = line[:m.start()]
        after = line[m.end():]
        consumer = _first_word(before)
        shell_ctx = consumer in _SHELL_INTERPS or any(
            _first_word(seg) in _SHELL_INTERPS for seg in after.split("|")[1:]
        )
        out.append(line)
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip() != delim:
            body.append(lines[i])
            i += 1
        out.extend(body if shell_ctx else ["" for _ in body])
        if i < len(lines):
            out.append(lines[i])
            i += 1
    return "\n".join(out)


if __name__ == "__main__":
    print(strip_non_executable_contexts(os.environ.get("CMD_INPUT", "")))
