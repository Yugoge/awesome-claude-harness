"""The tree a lint runs on: its prompts, its registered hooks and its ledger rows.

The settings and ledger parsing is scripts/check-enforcement-evidence.py's own (the gate
that already holds docs/ENFORCEMENT-LEDGER.md to settings.json), loaded from this
checkout, so the lint and that gate read one table one way.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER = "docs/ENFORCEMENT-LEDGER.md"
SETTINGS = "settings.json"
# The prompt corpus: what the CLI loads as instructions. README.md and INDEX.md in these
# folders are folder documentation the doc-sync hook maintains, not prompts.
PROMPT_DIRS = ("commands", "agents")
PROMPT_FILES = ("CLAUDE.md",)
FOLDER_DOCS = {"README.md", "INDEX.md"}
SCRIPT_RE = re.compile(r"""([^\s"']+\.(?:py|sh))""")


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    line: int
    message: str

    def text(self) -> str:
        return f"{self.path}:{self.line}: [{self.check}] {self.message}"


@dataclass(frozen=True)
class Registration:
    event: str
    matcher: str
    path: str       # tree-relative path of the script the command runs


@functools.lru_cache(maxsize=1)
def evidence_module():
    """scripts/check-enforcement-evidence.py, the ledger gate whose table parser this reuses."""
    path = REPO / "scripts" / "check-enforcement-evidence.py"
    spec = importlib.util.spec_from_file_location("_lint_enforcement_evidence", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def script_of(command: str) -> str | None:
    """The tree-relative script a hook command runs: its last *.py or *.sh word, with the
    harness-home prefix (`${CLAUDE_HOME:-$HOME/.claude}/`, `$HOME/.claude/`, `~/.claude/`) dropped."""
    found = SCRIPT_RE.findall(command or "")
    if not found:
        return None
    word = found[-1]
    word = re.sub(r"^.*\}/", "", word)
    word = re.sub(r"^(?:~|\$HOME|\$\{HOME\})/\.claude/", "", word)
    word = re.sub(r"^\$\{?CLAUDE_HOME\}?/", "", word)
    return word.lstrip("./") if not word.startswith("/") else word


class Tree:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()

    def abspath(self, rel: str) -> Path:
        return self.root / rel

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    @functools.lru_cache(maxsize=None)
    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8", errors="replace")

    def lines(self, rel: str) -> list[str]:
        return self.read(rel).split("\n")

    @functools.cached_property
    def prompts(self) -> list[str]:
        out = [f for f in PROMPT_FILES if (self.root / f).is_file()]
        for top in PROMPT_DIRS:
            base = self.root / top
            if not base.is_dir():
                continue
            for dirpath, dirs, files in os.walk(base):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(files):
                    if name.endswith(".md") and name not in FOLDER_DOCS:
                        out.append(os.path.relpath(os.path.join(dirpath, name), self.root))
        return sorted(out)

    @functools.cached_property
    def registrations(self) -> list[Registration]:
        path = self.root / SETTINGS
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for event, entries in (data.get("hooks") or {}).items():
            for entry in entries or []:
                matcher = (entry.get("matcher") or "").strip() or "(universal)"
                for hook in entry.get("hooks") or []:
                    rel = script_of(hook.get("command", ""))
                    if rel:
                        out.append(Registration(event, matcher, rel))
        return out

    @functools.cached_property
    def ledger_rows(self) -> list[dict]:
        """The registered-hook table of docs/ENFORCEMENT-LEDGER.md, one dict per row."""
        path = self.root / LEDGER
        if not path.is_file():
            return []
        ev = evidence_module()
        table = ev.select_table(ev.parse_tables(path.read_text(encoding="utf-8")), ev.REGISTERED_TABLE_KEY)
        return list(table["rows"]) if table else []

    @functools.cached_property
    def hook_names(self) -> set[str]:
        """Basenames a prompt may use for a hook: every registered script and every script
        directly under hooks/."""
        names = {os.path.basename(r.path) for r in self.registrations}
        hooks = self.root / "hooks"
        if hooks.is_dir():
            names |= {f for f in os.listdir(hooks) if f.endswith((".py", ".sh"))}
        return names

    def ignored(self, rels: list[str]) -> set[str]:
        """The paths git ignores in this tree: runtime files of the harness home (venv/, logs/,
        todos/ ...), which a prompt may name though no checkout holds them."""
        if not rels:
            return set()
        try:
            proc = subprocess.run(["git", "-C", str(self.root), "check-ignore", "--no-index", "--stdin"],
                                  input="\n".join(rels) + "\n", capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return set()
        return {line.strip() for line in proc.stdout.splitlines() if line.strip()}
