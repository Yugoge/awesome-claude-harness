"""Additive recognizer for statically named agent write destinations.

This module is deliberately not an authorization hook and never emits
``updatedInput``.  It reports decidable targets and recognized-but-unresolved
explicit destinations so the POL/BIND owners can fail closed consistently.
Opaque child syscalls remain outside the static boundary and are contained only
by the actor-owned managed temp environment.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Iterable


_DYNAMIC_RE = re.compile(r"(?:\$\{|\$[A-Za-z_(]|`|[*?\[])" )
_REDIRECT_RE = re.compile(
    r"(?<![0-9])(?:>>|>\||>)(?!&)[ \t]*(?P<target>[^\s;&|]+)"
)
_PYTHON_OPEN_RE = re.compile(
    r"\bopen\(\s*(['\"])(?P<path>.+?)\1\s*,\s*(['\"])[wax](?:[bt+]*)\3"
)
_PYTHON_PATH_RE = re.compile(
    r"\bPath\(\s*(['\"])(?P<path>.+?)\1\s*\)\s*\.\s*"
    r"(?:write_text|write_bytes|touch|mkdir)\s*\("
)
_NODE_RE = re.compile(
    r"\b(?:fs\.)?(?:writeFileSync|appendFileSync|mkdirSync)\(\s*"
    r"(['\"])(?P<path>.+?)\1"
)


def _tokens(command: str) -> tuple[list[str], bool]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer), True
    except ValueError:
        return [], False


def _segments(tokens: Iterable[str]) -> list[list[str]]:
    output: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {";", "&&", "||", "|", "&", "\n"}:
            if current:
                output.append(current)
                current = []
        else:
            current.append(token)
    if current:
        output.append(current)
    return output


def _command_index(segment: list[str]) -> int | None:
    index = 0
    while index < len(segment):
        token = segment[index]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            index += 1
            continue
        if Path(token).name in {"env", "command", "builtin", "nohup"}:
            index += 1
            while index < len(segment) and segment[index].startswith("-"):
                index += 1
            continue
        return index
    return None


def _operand_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token and not token.startswith("-")]


def analyze_command(command: str) -> dict:
    """Return deterministic static targets and unresolved explicit syntax."""

    if not isinstance(command, str):
        return {
            "status": "fail",
            "targets": [],
            "unresolved": [{"expression": None, "mechanism": "command", "reason": "not_string"}],
            "parse_ok": False,
            "opaque_runtime_boundary": True,
        }

    candidates: list[tuple[str, str]] = []
    for match in _REDIRECT_RE.finditer(command):
        candidates.append((match.group("target").strip("'\""), "redirect"))
    for regex, mechanism in (
        (_PYTHON_OPEN_RE, "python-open"),
        (_PYTHON_PATH_RE, "python-pathlib"),
        (_NODE_RE, "node-fs"),
    ):
        for match in regex.finditer(command):
            candidates.append((match.group("path"), mechanism))

    tokens, parse_ok = _tokens(command)
    for segment in _segments(tokens):
        command_index = _command_index(segment)
        if command_index is None:
            continue
        utility = Path(segment[command_index]).name
        args = segment[command_index + 1 :]
        if utility == "tee":
            candidates.extend((value, "tee") for value in _operand_tokens(args))
        elif utility in {"cp", "mv", "install", "rsync", "ln"}:
            operands = _operand_tokens(args)
            if operands:
                candidates.append((operands[-1], utility))
        elif utility == "sed" and any(
            value == "-i" or value.startswith("-i") for value in args
        ):
            operands = _operand_tokens(args)
            if len(operands) >= 2:
                candidates.extend((value, "sed-inplace") for value in operands[1:])
        elif utility in {"mkdir", "touch", "truncate"}:
            candidates.extend((value, utility) for value in _operand_tokens(args))
        elif utility == "mktemp":
            index = 0
            while index < len(args):
                value = args[index]
                if value.startswith("--tmpdir="):
                    candidates.append((value.split("=", 1)[1], "mktemp-tmpdir"))
                elif value == "--tmpdir" and index + 1 < len(args):
                    candidates.append((args[index + 1], "mktemp-tmpdir"))
                    index += 1
                elif not value.startswith("-"):
                    candidates.append((value, "mktemp-template"))
                index += 1
        elif utility == "dd":
            for value in args:
                if value.startswith("of="):
                    candidates.append((value[3:], "dd-output"))
        elif utility == "curl":
            for index, value in enumerate(args):
                if value in {"-o", "--output"} and index + 1 < len(args):
                    candidates.append((args[index + 1], "curl-output"))
                elif value.startswith("--output="):
                    candidates.append((value.split("=", 1)[1], "curl-output"))
        elif utility == "wget":
            for index, value in enumerate(args):
                if value in {"-O", "--output-document"} and index + 1 < len(args):
                    candidates.append((args[index + 1], "wget-output"))
                elif value.startswith("--output-document="):
                    candidates.append((value.split("=", 1)[1], "wget-output"))

    targets: list[dict] = []
    unresolved: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for expression, mechanism in candidates:
        expression = expression.strip()
        key = (expression, mechanism)
        if not expression or key in seen:
            continue
        seen.add(key)
        if _DYNAMIC_RE.search(expression):
            unresolved.append(
                {
                    "expression": expression,
                    "mechanism": mechanism,
                    "reason": "dynamic_explicit_destination",
                }
            )
        else:
            targets.append({"path": expression, "mechanism": mechanism})
    if not parse_ok and ("/tmp" in command or "/var/tmp" in command or "$TMP" in command):
        unresolved.append(
            {
                "expression": command,
                "mechanism": "shell-parse",
                "reason": "recognized_temp_syntax_parse_error",
            }
        )
    return {
        "status": "pass" if parse_ok else "fail",
        "targets": targets,
        "unresolved": unresolved,
        "parse_ok": parse_ok,
        "opaque_runtime_boundary": True,
    }


def extract_agent_temp_targets(command: str) -> list[str]:
    """Compatibility helper returning only statically decidable paths."""

    return [entry["path"] for entry in analyze_command(command)["targets"]]


def has_unresolved_explicit_temp(command: str) -> bool:
    return bool(analyze_command(command)["unresolved"])


__all__ = [
    "analyze_command",
    "extract_agent_temp_targets",
    "has_unresolved_explicit_temp",
]
