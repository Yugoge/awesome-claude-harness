#!/usr/bin/env python3
"""The one list of file names that hold secrets, matched by exact base name, never by substring.

A path is sensitive when its base name (the text after the last `/`, case folded) is one of:

- an environment file: `.env`, `.env.<anything>` (`.env.local`, `.env.production`), `<anything>.env`
  (`prod.env`) or `.envrc`;
- an SSH private key: `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `id_ecdsa_sk`, `id_ed25519_sk` (not `.pub`);
- a secret store: a stem that is, or ends after `-`, `_` or `.` in, `credential(s)`, `secret(s)` or
  `password(s)` (`credentials`, `.git-credentials`, `client_secret`, `db_password`), leading dots ignored, with
  no extension or only data extensions (`DATA_EXTENSIONS`: `secrets.yaml`, `passwords.csv`,
  `.credentials.json`, `secrets.enc.yaml`).

So `test_password_reset.py`, `test_auth_password.py` (code, not data), `secret-scan-report.txt` and
`password-policy` (the stem goes on past the word) are not sensitive. A word computed at run time is read by its
static text, quotes dropped: `"$HOME/.env"` is `.env`.

`RAW_FALLBACK_WRITE` and `RAW_FALLBACK_READ` are the substring patterns a caller that cannot parse a command
judges its raw text by, so a command no parser reads is refused more, never less.

Callers: hooks/lib/bash_safety_rules.py (sensitive_redirect).
"""
import re

ENV_EXACT = frozenset({".env", ".envrc"})
PRIVATE_KEY_NAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk"})
SECRET_STEM = re.compile(r"^(?:.*[-_.])?(?:credentials?|secrets?|passwords?)$")
DATA_EXTENSIONS = frozenset({
    "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "config", "env", "txt", "csv", "tsv", "properties",
    "xml", "plist", "key", "pem", "gpg", "asc", "age", "enc", "bak", "old", "orig", "local", "dat", "db",
    "kdbx", "p12", "pfx", "jks",
})

RAW_FALLBACK_WRITE = re.compile(r"(>|>>)\s*\S*(\.env|credential|secret|password|id_rsa|id_dsa|id_ecdsa|id_ed25519)",
                                re.IGNORECASE)
RAW_FALLBACK_READ = re.compile(r"(\.env|credential|secret|password|id_rsa|id_dsa|id_ecdsa|id_ed25519)\S*\s*(>|>>)",
                               re.IGNORECASE)


def base_name(text):
    """The base name of a path or a word's static text: quotes dropped, the part after the last `/`."""
    return (text or "").replace('"', "").replace("'", "").rstrip("/").rsplit("/", 1)[-1]


def is_sensitive_name(path):
    """True when the base name of `path` is on the list above."""
    name = base_name(path).lower()
    if not name:
        return False
    if name in ENV_EXACT or name.startswith(".env.") or name.endswith(".env") or name in PRIVATE_KEY_NAMES:
        return True
    stem, _, ext = name.lstrip(".").partition(".")
    if not SECRET_STEM.match(stem):
        return False
    return not ext or all(part in DATA_EXTENSIONS for part in ext.split("."))
