#!/usr/bin/env python3
"""The one definition of a path or word that may name a secret file.

The default is the substring rule bash-safety has always had, made case-insensitive: a text is sensitive when it
contains `.env`, `credentials`, `secret` or `password` anywhere, the full path included, not only the base name
(`secrets/prod.yaml`, `.password-store/foo.gpg`, `.env-prod`, `prod.env.bak`, `mysecrets.yaml`, `credentials.py`).
An SSH private key name (`id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, their `_sk` forms, anything after them but
`.pub`) is sensitive too.

That default is lifted only by these narrow exemptions, and only for a plain static path (no quote, space,
expansion, glob or brace left in it) whose directories carry none of the words:

- a URL (`scheme://...`) is no file name;
- a test file: a base name `test_*.<code>`, `*_test.<code>`, `*.test.<code>` or `*.spec.<code>`
  (`test_password_reset.py`, `auth_password_test.go`);
- a report or log: a base name containing `report` or ending in `.log` (`secret-scan-report.txt`);
- a template: a base name ending in `.example`, `.sample`, `.template` or `.dist` (`.env.example`).

`is_code_file` tells a source-code file (`src/password.ts`) apart, for a caller that reads a copy's source
operand: copying code is no secret read, though writing over it under a secret name stays one.

A word computed at run time (`$X`, `$(...)`, backticks, globs, braces) or interpreter code is judged by
substring on its raw text, with no exemption: `> .env$X`, `> $(echo .env)` and `python3 -c 'open(".env")'` stay
sensitive.

`RAW_FALLBACK_WRITE` and `RAW_FALLBACK_READ` are the substring patterns a caller that cannot parse a command
judges its raw text by, so a command no parser reads is refused more, never less.

Callers: hooks/lib/bash_safety_rules.py (sensitive_redirect).
"""
import re

SECRET_SUBSTRING = re.compile(r"\.env|credentials|secret|password", re.IGNORECASE)
PRIVATE_KEY = re.compile(r"^id_(?:rsa|dsa|ecdsa|ed25519)(?:_sk)?(?!.*\.pub$)", re.IGNORECASE)
URL = re.compile(r"^[a-z][a-z0-9+.-]*://\S+$", re.IGNORECASE)
# A plain static path: nothing a shell would still expand or split.
PLAIN_PATH = re.compile(r"^[A-Za-z0-9_.+@%,:=~/-]+$")
CODE_EXT = (r"(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|mts|cts|go|rb|rs|java|kt|kts|scala|swift|php|c|cc|cpp|cxx|h|hpp|"
            r"cs|fs|ex|exs|erl|lua|pl|pm|r|jl|dart|sh|bash|zsh|vue|svelte)")
CODE_FILE = re.compile(r"\.%s$" % CODE_EXT, re.IGNORECASE)
TEST_FILE = re.compile(r"^(?:test_.+\.%s|.+_test\.%s|.+\.(?:test|spec)\.%s)$" % (CODE_EXT, CODE_EXT, CODE_EXT),
                       re.IGNORECASE)
REPORT_OR_LOG = re.compile(r"report|\.log$", re.IGNORECASE)
TEMPLATE = re.compile(r"\.(?:example|sample|template|dist)$", re.IGNORECASE)

RAW_FALLBACK_WRITE = re.compile(r"(>|>>)\s*\S*(\.env|credential|secret|password|id_rsa|id_dsa|id_ecdsa|id_ed25519)",
                                re.IGNORECASE)
RAW_FALLBACK_READ = re.compile(r"(\.env|credential|secret|password|id_rsa|id_dsa|id_ecdsa|id_ed25519)\S*\s*(>|>>)",
                               re.IGNORECASE)


def base_name(text):
    """The part of a path after the last `/` (trailing slashes ignored)."""
    return (text or "").rstrip("/").rsplit("/", 1)[-1]


def _exempt(name):
    return bool(TEST_FILE.match(name) or REPORT_OR_LOG.search(name) or TEMPLATE.search(name))


def is_code_file(text):
    """True when the base name of a plain static path ends in a source-code extension (`src/password.ts`)."""
    return bool(text) and bool(PLAIN_PATH.match(text)) and bool(CODE_FILE.search(base_name(text)))


def is_sensitive_name(text, computed=False):
    """True when `text` may name a secret file, by the rule above.

    `text` is a path or a word's static value; `computed=True` says it is a word's raw text because its value is
    not known before it runs, which gets the substring check alone.
    """
    if not text:
        return False
    if not computed and URL.match(text):
        return False
    if computed or not PLAIN_PATH.match(text):
        return bool(SECRET_SUBSTRING.search(text) or any(PRIVATE_KEY.match(p) for p in re.split(r"[/\s'\"=]", text)))
    name = base_name(text)
    head = text[:len(text.rstrip("/")) - len(name)]
    if SECRET_SUBSTRING.search(head):
        return True
    if PRIVATE_KEY.match(name):
        return True
    return bool(SECRET_SUBSTRING.search(name)) and not _exempt(name)
