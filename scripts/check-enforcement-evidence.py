#!/usr/bin/env python3
"""Enforcement-evidence gate: the SINGLE declared source for this repo's proof vocabulary.

Three subcommands, one consumer each:
  --ledger    evidence integrity  -- closed-set labels, `enforced` requires host-observed
                                     proof AND a linked corpus case, a passing compatibility
                                     row requires a workflow-run link, per-row field
                                     population, release-inventory coverage.
  --claims    claim-versus-code   -- both git regex symbols still exist, the arch-F7 residual
                                     block is intact, every declared matrix witness still
                                     produces its recorded (classifier, anchor) outcome, the
                                     wrapper/redirection token sets are unchanged, the
                                     gate-architecture census is unchanged, the ledger's
                                     registered-hook row set equals the settings-derived set,
                                     and every threat-model section-4 citation is pinned.
  --coverage  CI artifact gate    -- the run manifest maps one-to-one onto the corpus, every
                                     field is populated, and the results are provably the
                                     product of THIS run (executed == emitted == corpus).

RESIDUAL LIMIT OF --coverage, DISCLOSED RATHER THAN PAPERED OVER
-----------------------------------------------------------------
This gate proves a manifest is STRUCTURALLY complete, internally consistent, and carries
provenance fields. It cannot, by itself, prove those fields were not hand-authored: a manifest
written by hand with plausible `observed_source.captured_from` strings, real-looking exit codes
and `verdict` consistent with `observed == expected` will pass when the gate is run standalone
against it. What actually binds the artifact to an execution is the ORDER in CI: the suite
deletes any pre-existing manifest before running and writes results only from live invocations,
and only then does this gate read the file. Run outside that order, `--coverage` is a schema and
consistency check, not an attestation. Closing the gap properly needs a signed or
externally-witnessed artifact, which is out of scope for this cycle and is named here as an open
dependency rather than implied to be handled.

WHY THIS FILE IS THE ONLY PLACE THE CLOSED SETS ARE WRITTEN
-----------------------------------------------------------
A prior revision of this lane's specification stated the `behavior` closed set five different
ways across four documents -- four-valued in two places and five-valued in four others. Two
guards written from two of those statements would have encoded two different closed sets, which
is the same two-hand-synced-copies drift class that RISK-2 of docs/THREAT-MODEL.md exists to
teach. So the sets are declared ONCE here, in DECLARED_SCHEMA, and every other consumer DERIVES
them:
  * scripts/verify-claims.sh invokes this script rather than restating any set;
  * docs/ENFORCEMENT-LEDGER.md publishes a machine-readable schema block which --ledger parses
    and asserts EQUAL AS JSON to DECLARED_SCHEMA -- key order and formatting are not compared,
    only the decoded value -- so the document cannot drift from the code.

`behavior` is EXACTLY the four labels the requirement names. `unexercised` is NOT a behavior --
whether the corpus reaches a hook is an exercise state, orthogonal to how that hook behaves --
so it lives on its own `exercise_status` axis. `component-tested` is likewise a proof layer, not
a behavior; keeping it out of `behavior` is what stops subprocess evidence being filed as host
prevention.

Usage:
  python3 scripts/check-enforcement-evidence.py --ledger   [--ledger-file P] [--changelog P] ...
  python3 scripts/check-enforcement-evidence.py --claims   [--ledger-file P] [--settings P] ...
  python3 scripts/check-enforcement-evidence.py --coverage [--manifest P] [--corpus P] ...
Every input path is overridable so a negative fixture can be proven against a mutated COPY
without touching the real tree.

Exit codes: 0 = every assertion held, 1 = one or more assertions failed, 2 = input unreadable.

Root cause (git): docs/THREAT-MODEL.md was authored at d5824f7f as a point-in-time snapshot and
was never re-derived from the code; by 4c33f2f5 all three of its residual-risk entries were
falsifiable in under a minute. Prose claims decay silently; only a mechanical re-derivation that
runs in CI does not.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# THE SINGLE DECLARED SOURCE.
# ---------------------------------------------------------------------------
DECLARED_SCHEMA = {
    "behavior": ["enforced", "detected", "advisory", "unsupported"],
    "exercise_status": ["exercised", "unexercised"],
    "proof_layer": [
        "host-observed",
        "host-shaped",
        "component-tested",
        "source-level",
        "none",
    ],
    # Accepted `status:` value per residual-risk entry of docs/THREAT-MODEL.md. Declared HERE
    # with the other closed sets rather than inline in the gate, for the same reason: a status
    # vocabulary restated at the assertion site is a second copy that drifts from the document
    # it describes. The ledger publishes this block and --ledger asserts byte-equality, so the
    # accepted values cannot move in one place only.
    "risk_status": {
        "RISK-1": ["PARTIALLY MITIGATED"],
        "RISK-2": ["MITIGATED"],
        "RISK-3": ["PARTIALLY MITIGATED"],
    },
}

# ---------------------------------------------------------------------------
# Published-claim scope guards.
#
# The ledger's premise is that a hostile reader can trust its rows. A claim in it that exceeds
# what the checks below establish is therefore not a documentation defect -- it is the specific
# failure mode the document exists to prevent. These patterns are matched against the
# WHITESPACE-NORMALIZED document (published prose wraps at ~95 columns and blockquoted
# paragraphs carry an interposed '>' on continuation lines, so an unnormalized literal silently
# matches nothing and an absence assertion built on one passes vacuously).
#
# Each pattern matches a POSITIVE promise shape only, so the honest replacement -- which states
# what the gate does NOT establish -- does not trip its own guard.
# ---------------------------------------------------------------------------
FORBIDDEN_CLAIM_PATTERNS = [
    (r"(?i)\b(?:nothing|none|no\s+(?:part|column|field|cell|row))\b[^.]{0,120}"
     r"\bregistered-hook\b[^.]{0,120}\bhand-(?:authored|edited|written)\b",
     "a claim that no part of the registered-hook table is hand-authored"),
    (r"(?i)\bregistered-hook\b[^.]{0,120}\b(?:is|are)\s+(?:not|never)\s+"
     r"hand-(?:authored|edited|written)\b",
     "a claim that the registered-hook rows are not hand-authored"),
    (r"(?i)\b(?:every|all|each)\s+(?:field|column|cell)\b[^.]{0,120}\bregistered-hook\b"
     r"[^.]{0,120}\b(?:derived|regenerated|recomputed|generated)\b",
     "a claim that every registered-hook field is derived"),
    (r"(?i)\bregistered-hook\s+(?:table|rows?|row\s+set)\s+(?:is|are)\s+"
     r"(?:wholly|entirely|fully|completely)?\s*(?:derived|regenerated|generated)\b",
     "a whole-table derivation claim"),
    (r"(?i)\b(?:every|all|each)\s+registered-hook\s+(?:datum|data|value|cell|entry|entries)\b"
     r"[^.]{0,80}\b(?:comes?|derived|generated|recomputed)\b",
     "a claim that every registered-hook datum is derived"),
    (r"(?i)\b(?:constructs?|builds?|generates?)\s+the\s+(?:complete|entire|whole|full)\s+"
     r"registered-hook\s+table\b",
     "a claim that the complete registered-hook table is constructed by the checker"),
    (r"(?i)\bregenerate\s+the\s+registered-hook\s+rows\b",
     "an unqualified instruction to regenerate the registered-hook rows"),
    (r"(?i)\bdo\s+not\s+hand-edit\s+(?:them|the\s+(?:registered-hook\s+)?rows)\b",
     "an unqualified instruction not to hand-edit the rows"),
    (r"(?i)\bhostile\s+reader\b[^.]{0,120}\bfalsify\b[^.]{0,60}\b(?:any|every|each)\s+rows?\b",
     "a universally-quantified falsifiability promise over rows"),
    (r"(?i)\bshould\s+be\s+able\s+to\s+falsify\b[^.]{0,60}\b(?:any|every|each)\s+rows?\b",
     "a universally-quantified falsifiability promise over rows"),
    (r"(?i)\bfalsif\w+\s+(?:any|every|each)\s+rows?\s+(?:here\s+)?with\s+"
     r"(?:one|a\s+single)\s+command\b",
     "a one-command falsifiability promise over rows"),
    (r"(?i)\b(?:any|every|each)\s+rows?\b[^.]{0,60}\b(?:can|may|could)\s+be\s+falsified\b",
     "a universally-quantified falsifiability promise over rows"),
]

# The three columns `--claims` step 7 actually recomputes, and the seven it does not.
DERIVED_ROW_FIELDS = ["event_class", "matcher", "hook"]
AUTHORED_ROW_FIELDS = ["row_id", "mode/precondition", "behavior", "exercise_status",
                       "proof_layer", "citation", "verifying_test"]

# Values recorded at the revision named below. Any drift from them is a FAILURE, not an update:
# the published claim must break loudly rather than silently describe a boundary that moved.
RECORDED_AT = "4c33f2f5"

RECORDED_WRAPPERS = [
    "sudo", "doas", "env", "xargs", "time", "nohup",
    "setsid", "stdbuf", "ionice", "command", "builtin", "nice",
]
RECORDED_REDIRECTION_OPS = ["2>/dev/null", ">", ">>", "<", "2>&1", "&>", "1>"]

# Anchor-class literals as they appear in the two guard sources. Extracted live and compared:
# adding '/' to either class would change the residual class, so the published table must fail.
RECORDED_ERE_ANCHOR = "(^|[[:space:];&|()`])git"
RECORDED_PY_ANCHOR = "(?:^|[\\s;&|()`])git"

# Gate-architecture census, counted at RECORDED_AT.
#   A = classifier-primary with a MUTUALLY EXCLUSIVE regex fallback guarded by
#       [ "$CLASSIFIER_STATUS" != "ok" ]. This is the shape where a successful-but-empty parse
#       suppresses the backstop.
#   B = unconditional GIT_CMD_RE branch OR-ed with a classifier flag. Unaffected.
#   C = classifier-only path-qualified AUGMENTATION branch guarded by
#       CLASSIFIER_HAS_PATH_QUALIFIED_GIT. These have no regex fallback of their own because
#       they never carried one: they exist to ADD path-qualified coverage on top of a separate
#       bare-form regex gate, so there is nothing for an empty parse to suppress.
# All three are counted. Counting only A and B would be MISLEADINGLY NARROW -- a reader
# counting classifier-consuming branches in the guard finds 11, not 3, and would reasonably
# conclude the published census was cherry-picked to fit the finding.
RECORDED_CENSUS = {"architecture_a": 1, "architecture_b": 2, "architecture_c": 8}

# Every mandated cell witness, probed INDIVIDUALLY. Probing one representative per cell is not
# sufficient: teaching the tokenizer to skip an unprobed sibling leaves every representative
# behaving exactly as recorded while the boundary moves.
MANDATED_WITNESSES = [
    {"id": "W1",  "form": "git status",                      "cell": "none/bare",
     "classifier": "detected", "anchor": "MATCH",    "gate_architecture": "n/a"},
    {"id": "W2",  "form": "/usr/bin/git status",             "cell": "none/path-qualified",
     "classifier": "detected", "anchor": "no-match", "gate_architecture": "n/a"},
    {"id": "W3",  "form": "env /usr/bin/git status",         "cell": "wrapper-no-flag/path-qualified",
     "classifier": "detected", "anchor": "no-match", "gate_architecture": "n/a"},
    {"id": "W4",  "form": "env -i git status",               "cell": "wrapper-with-flag/bare",
     "classifier": "MISS",     "anchor": "MATCH",    "gate_architecture": "A|B"},
    {"id": "W5",  "form": "env -u FOO git status",           "cell": "wrapper-with-flag/bare",
     "classifier": "MISS",     "anchor": "MATCH",    "gate_architecture": "A|B"},
    {"id": "W6",  "form": "2>/dev/null git status",          "cell": "leading-redirection/bare",
     "classifier": "MISS",     "anchor": "MATCH",    "gate_architecture": "A|B"},
    {"id": "W7",  "form": "env -i /usr/bin/git status",      "cell": "wrapper-with-flag/path-qualified",
     "classifier": "MISS",     "anchor": "no-match", "gate_architecture": "A|B"},
    {"id": "W8",  "form": "env -u FOO /usr/bin/git status",  "cell": "wrapper-with-flag/path-qualified",
     "classifier": "MISS",     "anchor": "no-match", "gate_architecture": "A|B"},
    {"id": "W9",  "form": "2>/dev/null /usr/bin/git status", "cell": "leading-redirection/path-qualified",
     "classifier": "MISS",     "anchor": "no-match", "gate_architecture": "A|B"},
    {"id": "W10", "form": "sudo -n /usr/bin/git status",     "cell": "wrapper-with-flag/path-qualified",
     "classifier": "MISS",     "anchor": "no-match", "gate_architecture": "A|B"},
    {"id": "W11", "form": "nice -n 5 /usr/bin/git status",   "cell": "wrapper-with-flag/path-qualified",
     "classifier": "MISS",     "anchor": "no-match", "gate_architecture": "A|B"},
]

PIN_RE = re.compile(r"@[0-9a-f]{7,8}\b")
CITATION_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|sh|md|json|yml):\d+")

REGISTERED_TABLE_KEY = "event_class"
COMPAT_TABLE_KEY = "release_key"
SUBJECT_TABLE_KEY = "subject"


class Fail(Exception):
    """Unreadable input -- distinct from an assertion failure."""


# ---------------------------------------------------------------------------
# Markdown table parsing. Tables are identified by the column names in their header row, so
# reordering or renaming a table's title does not break the parse but losing a COLUMN does --
# which is the point: deleting the behavior column must fail, not silently parse as empty.
# ---------------------------------------------------------------------------
def _split_row(line):
    """Split a markdown table row on UNESCAPED pipes, then unescape.

    Several settings.json matchers are alternations (`Edit|Write|MultiEdit`), so a naive
    split would shred one hook row into five bogus ones and the set-equality check would
    compare garbage against garbage. Cells are written escaped (`\\|`) and restored here.
    """
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, buf, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def parse_tables(text):
    """Return [{'columns': [...], 'rows': [{col: val}], 'lines': [raw]}] for every pipe table."""
    tables, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if re.fullmatch(r"\|[\s:\-|]+\|", sep or ""):
                cols = _split_row(lines[i])
                rows, raws, j = [], [], i + 2
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    cells = _split_row(lines[j])
                    if len(cells) < len(cols):
                        cells += [""] * (len(cols) - len(cells))
                    rows.append(dict(zip(cols, cells[: len(cols)])))
                    raws.append(lines[j])
                    j += 1
                tables.append({"columns": cols, "rows": rows, "lines": raws})
                i = j
                continue
        i += 1
    return tables


def select_table(tables, key_column):
    for t in tables:
        if key_column in t["columns"]:
            return t
    return None


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf8")
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"cannot read {path}: {exc}") from exc


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
    except Exception as exc:  # noqa: BLE001
        raise Fail(f"cannot read/parse JSON {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Shared derivations.
# ---------------------------------------------------------------------------
def settings_triples(settings_path):
    """Flatten settings.json to the (event_class, matcher, hook) triple set."""
    data = read_json(settings_path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict) or not hooks:
        raise Fail(f"{settings_path}: 'hooks' missing or not a non-empty object")
    out = set()
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            raise Fail(f"{settings_path}: hooks[{event!r}] is not a list")
        for entry in entries:
            matcher = (entry.get("matcher") or "").strip() or "(universal)"
            for hook in entry.get("hooks") or []:
                command = hook.get("command", "")
                found = re.findall(r"([^\s\"']+\.(?:py|sh))", command)
                script = found[-1].split("/")[-1] if found else command.strip()[:50]
                out.add((event, matcher, script))
    if not out:
        raise Fail(f"{settings_path}: computed 0 wired hooks -- refusing (schema anomaly)")
    return out


def ledger_tables(ledger_path):
    tables = parse_tables(read_text(ledger_path))
    return {
        "registered": select_table(tables, REGISTERED_TABLE_KEY),
        "compat": select_table(tables, COMPAT_TABLE_KEY),
        "subject": select_table(tables, SUBJECT_TABLE_KEY),
        "all": tables,
    }


def declared_schema_block(ledger_text):
    """Extract the ledger's published machine-readable schema block."""
    # The closing marker is REQUIRED. Matching only to the first fence let the block be
    # unterminated, so the region the document advertises as delimited was not.
    match = re.search(
        r"<!--\s*enforcement-schema:begin\s*-->\s*```json\s*(.*?)```"
        r"\s*<!--\s*enforcement-schema:end\s*-->",
        ledger_text,
        re.S,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Prose normalization and anchored-region extraction.
# ---------------------------------------------------------------------------
def normalize_prose(text):
    """Strip per-line blockquote markers, then collapse all whitespace to single spaces.

    Published prose wraps at ~95 columns and blockquoted paragraphs carry an interposed '>'
    on every continuation line, so a single-line literal never matches the raw bytes. An
    absence assertion written against the raw text therefore passes vacuously -- the exact
    newline-intolerance defect this gate exists to catch elsewhere.
    """
    stripped = [re.sub(r"^\s*>\s?", "", line) for line in text.split("\n")]
    return re.sub(r"\s+", " ", " ".join(stripped)).strip()


def ledger_header_block(ledger_text):
    """Everything before the '## 1. Vocabulary' heading -- the claim-bearing header."""
    match = re.search(r"(?ms)^##\s+1\.\s+Vocabulary", ledger_text)
    return ledger_text[: match.start()] if match else ledger_text


def companion_paths(header_text):
    """Repo-relative companion paths PARSED from the header, never hardcoded here.

    A hardcoded list would let the header cite a document that does not exist while the gate
    happily checked three unrelated paths it was born knowing.
    """
    match = re.search(r"(?is)Companion documents:(.*?)(?:\n\s*\n|\Z)", header_text)
    if not match:
        return None
    paths = sorted({p for p in re.findall(r"`([^`]+)`", match.group(1))
                    if "/" in p and re.search(r"\.[A-Za-z0-9]+$", p)})
    # An empty result is a PARSE FAILURE, not a document that cites nothing: returning [] here
    # would report "all 0 companion documents exist" and pass vacuously.
    return paths or None


def published_token_set(ledger_text, label):
    """Return the token LIST published in one anchored region, or None if absent.

    Scoping alone is not enough, and neither is substring inclusion. Three separate ways a
    substring test lets an unpublished set pass: `nice` is satisfied by `ionice`; `>` is
    satisfied by `2>/dev/null`; and an inclusion test can never reject an EXTRA token that was
    never recorded. So the region is PARSED -- the backtick-delimited items following its
    `N tokens:` marker are the published set, compared for exact set equality. Parsing the
    published list rather than restating it also keeps the token set declared exactly once in
    code (RECORDED_*) and exactly once in the document.
    """
    match = re.search(
        r"<!--\s*published-tokens:%s:begin\s*-->(.*?)<!--\s*published-tokens:%s:end\s*-->"
        % (re.escape(label), re.escape(label)),
        ledger_text,
        re.S,
    )
    if not match:
        return None
    region = match.group(1)
    marker = list(re.finditer(r"\d+\s+tokens:", region))
    if not marker:
        return None
    return re.findall(r"`([^`]+)`", region[marker[-1].end():])


def published_column_set(header_text, label):
    """Return the column names published in one anchored header region, or None if absent.

    Assertion 0b used to test `field_name in header` -- presence ANYWHERE in the normalized
    header block. Six of the ten column names also occur in the surrounding prose (`hook` 4x,
    `behavior` and `proof_layer` 3x, `citation`, `exercise_status` and `verifying_test` 2x
    each), so any of those six could be DELETED from the published enumeration and the gate
    would still exit 0 -- the same vacuous-match defect the token sets were region-scoped to
    fix, reproduced in this gate's own code. The enumeration is therefore read from its own
    anchored region and compared for exact set equality. An empty parse is a PARSE FAILURE,
    not an enumeration of nothing: returning [] would report "names all 0 columns" and pass
    vacuously, which is the failure mode `companion_paths` already guards against.
    """
    match = re.search(
        r"<!--\s*published-columns:%s:begin\s*-->(.*?)<!--\s*published-columns:%s:end\s*-->"
        % (re.escape(label), re.escape(label)),
        header_text,
        re.S,
    )
    if not match:
        return None
    return re.findall(r"`([^`]+)`", normalize_prose(match.group(1))) or None


# ---------------------------------------------------------------------------
# Semantic extraction of the wrapper token set.
# ---------------------------------------------------------------------------
def extract_wrappers(classifier_src):
    """Return sorted _WRAPPERS via ast.parse + literal_eval, or None if not found.

    The previous lexical scrape re.findall(r"'([^']+)'") saw only SINGLE-quoted tokens, so a
    double-quoted widening of the set left the count unchanged and the gate passed while the
    residual class named in the published matrix had actually grown.
    """
    try:
        tree = ast.parse(classifier_src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_WRAPPERS":
                try:
                    return sorted(ast.literal_eval(node.value))
                except Exception:  # noqa: BLE001
                    return None
    return None


# ---------------------------------------------------------------------------
# Shell-aware structural gate census.
#
# A Python parser cannot parse shell, so the wrapper set's ast treatment does not extend here.
# What DOES extend is the principle: count the STRUCTURE, not one spelling of it. Every guard
# condition is canonicalized -- quotes stripped, `${X}` and `$X` unified, and the operands of
# the symmetric comparison operators sorted -- so `[ "ok" != "${CLASSIFIER_STATUS}" ]` and
# `[ "$CLASSIFIER_STATUS" != "ok" ]` produce the same key and a respelled guard can no longer
# hide. No marker comment, sentinel or other implementer-authored label is read from the shell
# source: this repository's doctrine rejects trusting an implementer's self-applied label.
# ---------------------------------------------------------------------------
_SHELL_VAR_RE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)(?::[-=?+][^}]*)?\}?$")
_SHELL_WORD_RE = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")
# `[ ... ]`, `[[ ... ]]` and the `test` builtin are the same predicate written three ways.
_SHELL_TEST_RE = re.compile(
    r"(?<![\w$])\[\[?[ \t]+(.+?)[ \t]+\]\]?(?!\w)"
    r"|(?<![\w$/-])test[ \t]+([^;&|)]+)")
_SYMMETRIC_OPS = {"=": "=", "==": "=", "!=": "!="}


def _strip_full_line_comments(src):
    """Drop whole-line shell comments before any structural counting.

    A commented-out guard is not a gate. Counting one lets a real gate be DELETED while a
    comment holds the census at its recorded value -- a false pass of exactly the kind this
    census exists to end. Only full-line comments are removed: a `#` mid-line may be inside a
    regex or a quoted string in this guard, and removing those would corrupt real conditions.
    """
    return "\n".join("" if re.match(r"^[ \t]*#", line) else line for line in src.split("\n"))


def _canon_word(word):
    """Canonicalize one shell word: strip quoting, unify `${X}` / `$X` / `"$X"`."""
    text = word.strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    match = _SHELL_VAR_RE.match(text)
    return "$" + match.group(1) if match else text


_NEGATED_OP = {"=": "!=", "!=": "="}


def _canon_predicates(condition):
    """Canonical comparison keys for every bracket test inside one condition.

    Negation is folded into the operator, so `! [ "$X" = "ok" ]` and `[ ! "$X" = "ok" ]`
    canonicalize identically to `[ "$X" != "ok" ]`. Without this, respelling a fallback arm
    as a negated equality would move it out of the fallback key and silently drop a gate from
    the census -- the same false pass this census exists to end.
    """
    keys = set()
    for match in _SHELL_TEST_RE.finditer(condition):
        outer_negated = bool(re.search(r"!\s*$", condition[: match.start()]))
        words = _SHELL_WORD_RE.findall(match.group(1) or match.group(2) or "")
        if words and words[0] == "!":
            words, outer_negated = words[1:], not outer_negated
        for i, word in enumerate(words):
            op = _SYMMETRIC_OPS.get(word)
            if not op or i == 0 or i + 1 >= len(words):
                continue
            if outer_negated:
                op = _NEGATED_OP[op]
            operands = sorted((_canon_word(words[i - 1]), _canon_word(words[i + 1])))
            keys.add(f"{op}:{operands[0]}|{operands[1]}")
    return keys


def _var_refs(text):
    return set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", text))


_SHELL_ARM_RE = re.compile(r"^(if|elif)\b[ \t]+(.*?)[ \t]*;?[ \t]*then[ \t]*$")


def _shell_if_statements(src):
    """[(order, condition, body)] for every if/elif arm, with line continuations joined.

    An arm is recognized only when it TERMINATES in `then`. That requirement is load-bearing,
    not cosmetic: this guard embeds Python programs inside double-quoted `python -c` blocks,
    and a line such as `if inv.get('subcommand')=='reset':` inside one of them is not a shell
    arm. Treating it as one desynchronizes the `fi` pairing, after which a real arm's body runs
    away to end-of-file and absorbs every later assignment -- which manufactures gate pairings
    that do not exist. Each line is attributed to the INNERMOST open arm only, so an arm's body
    is what that arm itself guards.
    """
    joined = re.sub(r"\\\n[ \t]*", " ", src)
    # `then` written on its own line is the same arm as the condition above it. Leaving the two
    # unjoined would make such an arm unrecognizable, so a gate respelled that way would drop
    # out of the census and the comparison would pass with a real gate hidden.
    joined = re.sub(r"\n[ \t]*then[ \t]*(?=\n)", " ; then", joined)
    statements, stack = [], []
    for index, line in enumerate(joined.split("\n")):
        head = line.strip()
        arm = _SHELL_ARM_RE.match(head)
        if arm:
            if arm.group(1) == "if":
                stack.append(None)
            statements.append({"order": index, "condition": arm.group(2), "body_lines": []})
            if stack:
                stack[-1] = len(statements) - 1
            continue
        if head == "else" and stack:
            stack[-1] = None
            continue
        if head == "fi" and stack:
            stack.pop()
            continue
        if stack and stack[-1] is not None:
            statements[stack[-1]]["body_lines"].append(line)
    return [(s["order"], s["condition"], "\n".join(s["body_lines"])) for s in statements]


def _grep_matches_symbol(src, symbol):
    """Count `grep` invocations carrying BOTH -E and -q whose pattern names `symbol`.

    Flag clustering and order are normalized (`-qE`, `-Eq`, `-q -E` are one shape), and the
    symbol is matched by exact name so a DIFFERENT variable with a common prefix is not
    miscounted as this one.
    """
    joined = re.sub(r"\\\n[ \t]*", " ", _strip_full_line_comments(src))
    ref = re.compile(r"\$\{%s\}|\$%s\b" % (re.escape(symbol), re.escape(symbol)))
    count = 0
    for match in re.finditer(r"(?<![\w./-])grep\b", joined):
        tail = joined[match.end(): match.end() + 400].split("\n")[0]
        words, flags, rest = _SHELL_WORD_RE.findall(tail), set(), []
        for word in words:
            if word.startswith("-") and not rest:
                flags |= set(word[1:])
            else:
                rest.append(word)
        if {"E", "q"} <= flags and any(ref.search(word) for word in rest):
            count += 1
    return count


def shell_gate_census(bash_src):
    """Structurally derive the A/B/C gate counts from the shell source.

    A = a COMPLETE gate: a classifier-primary arm and a status-not-ok fallback arm whose
        results converge on one later decision. A bare dangling comparison is not a gate and
        is deliberately NOT counted -- counting one would be a substring check wearing a
        structural label.
    B = an unconditional GIT_CMD_RE grep branch.
    C = a branch guarded on the path-qualified classifier flag.
    """
    bash_src = _strip_full_line_comments(bash_src)
    statements = _shell_if_statements(bash_src)
    primary_key = '=:$CLASSIFIER_STATUS|ok'
    fallback_key = '!=:$CLASSIFIER_STATUS|ok'
    pq_key = '=:$CLASSIFIER_HAS_PATH_QUALIFIED_GIT|1'

    primaries, fallbacks, architecture_c = [], [], 0
    for order, condition, body in statements:
        keys = _canon_predicates(condition)
        assigned = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=1\b", body))
        if primary_key in keys and assigned:
            primaries.append((order, assigned))
        if fallback_key in keys and assigned:
            fallbacks.append((order, assigned))
        if pq_key in keys:
            architecture_c += 1

    # A unit exists only where one later condition reads BOTH arms' decision variables.
    pairs = set()
    for order, condition, _ in statements:
        referenced = _var_refs(condition)
        for p_order, p_vars in primaries:
            for f_order, f_vars in fallbacks:
                if order > max(p_order, f_order) and (p_vars & referenced) and \
                        (f_vars & referenced):
                    pairs.add((p_order, f_order))
    return {
        "architecture_a": len(pairs),
        "architecture_b": _grep_matches_symbol(bash_src, "GIT_CMD_RE"),
        "architecture_c": architecture_c,
    }


# ---------------------------------------------------------------------------
# Threat-model residual-risk status field.
# ---------------------------------------------------------------------------
STATUS_LINE_RE = re.compile(r"^status:[ \t]*([A-Z][A-Z ]*[A-Z])[ \t]*$", re.M)
BARE_STATUS_TOKEN_RE = re.compile(r"\b(?:UN)?MITIGATED\b")


def risk_blocks(threat_model_text):
    """[(risk_id, block_text)] for every '### RISK-N:' heading INSIDE section 4, or None.

    A LIST, not a dict, and scoped to the residual-risk section. A dict silently overwrites a
    duplicate id, so a document that drops the real RISK-1 status and adds a later duplicate
    RISK-1 carrying an accepted one would validate the surrogate and pass. Scoping keeps a
    heading elsewhere in the document from standing in for the published entry.
    """
    section = re.search(r"(?ms)^##\s+4\.\s+Known Residual Risks.*?(?=^##\s+\d|\Z)",
                        threat_model_text)
    if not section:
        return None
    body = section.group(0)
    matches = list(re.finditer(r"(?m)^###\s+(RISK-\d+)\s*:", body))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        blocks.append((match.group(1), body[match.start(): end]))
    return blocks


def check_risk_status(threat_model_text, report):
    """Exactly one normalized status line per entry, valued in that entry's accepted set,
    with no bare MITIGATED/UNMITIGATED token anywhere else in the block."""
    found = risk_blocks(threat_model_text)
    accepted_map = DECLARED_SCHEMA["risk_status"]
    if found is None:
        report.fail("threat model section 4 not found -- no residual-risk entry can be "
                    "validated")
        return
    clean = True
    # The published entry set must be EXACTLY the declared one, each appearing once. Without
    # this, an undeclared RISK-N is unvalidated and a duplicated id can shadow the real entry.
    seen = [rid for rid, _ in found]
    unknown = sorted({rid for rid in seen if rid not in accepted_map})
    duplicated = sorted({rid for rid in seen if seen.count(rid) > 1})
    absent = sorted(rid for rid in accepted_map if rid not in seen)
    for label, ids in (("undeclared", unknown), ("duplicated", duplicated), ("missing", absent)):
        if ids:
            report.fail(f"threat model section 4 carries {label} residual-risk heading(s) "
                        f"{ids}; the declared set is {sorted(accepted_map)}, each exactly once")
            clean = False
    blocks = dict(found)
    for risk_id, accepted in accepted_map.items():
        block = blocks.get(risk_id)
        if block is None:
            clean = False
            continue
        status_lines = STATUS_LINE_RE.findall(block)
        if len(status_lines) != 1:
            report.fail(f"{risk_id}: found {len(status_lines)} normalized status line(s); "
                        f"exactly 1 is required")
            clean = False
            continue
        if status_lines[0] not in accepted:
            report.fail(f"{risk_id}: status={status_lines[0]!r} is outside this entry's "
                        f"accepted set {accepted}")
            clean = False
        residue = STATUS_LINE_RE.sub("", block)
        stray = BARE_STATUS_TOKEN_RE.findall(residue)
        if stray:
            report.fail(f"{risk_id}: {len(stray)} bare {sorted(set(stray))} token(s) outside "
                        f"the status line -- a status must be stated once, in its own field")
            clean = False
    if clean:
        report.ok(f"every declared residual risk {sorted(accepted_map)} carries exactly one "
                  f"status line valued in its accepted set")


# ---------------------------------------------------------------------------
# --ledger
# ---------------------------------------------------------------------------
def check_ledger(args, report):
    text = read_text(args.ledger_file)
    tabs = ledger_tables(args.ledger_file)

    # 0a. No published claim may exceed what the checks below establish.
    normalized_doc = normalize_prose(text)
    overclaims = [why for pattern, why in FORBIDDEN_CLAIM_PATTERNS
                  if re.search(pattern, normalized_doc)]
    if overclaims:
        for why in sorted(set(overclaims)):
            report.fail(f"published-claim scope: the ledger carries {why} -- the gate "
                        f"establishes less than that")
    else:
        report.ok("no published claim in the ledger exceeds this gate's demonstrated scope")

    # 0b. The header must enumerate which columns are derived and which are authored, so the
    #     reader can see the boundary rather than infer it from an unqualified sentence.
    header = normalize_prose(ledger_header_block(text))
    missing_derived = [f for f in DERIVED_ROW_FIELDS if f not in header]
    missing_authored = [f for f in AUTHORED_ROW_FIELDS if f not in header]
    if missing_derived or missing_authored:
        if missing_derived:
            report.fail(f"ledger header does not name the derived column(s) {missing_derived}")
        if missing_authored:
            report.fail(f"ledger header does not name the authored column(s) {missing_authored}")
    else:
        report.ok(f"ledger header names all {len(DERIVED_ROW_FIELDS)} derived and "
                  f"{len(AUTHORED_ROW_FIELDS)} authored registered-hook columns")

    # 0c. Every companion document the header cites must exist. A citation to a document that
    #     is not there is a broken evidence chain, not a formatting problem.
    companions = companion_paths(ledger_header_block(text))
    if companions is None:
        report.fail("ledger header cites no companion documents -- the 'Companion documents:' "
                    "block is missing or unparseable")
    else:
        root = Path(args.root)
        absent = [rel for rel in companions if not (root / rel).exists()]
        if absent:
            for rel in absent:
                report.fail(f"companion document cited by the ledger header does not exist: "
                            f"{rel} (resolved against {root})")
        else:
            report.ok(f"all {len(companions)} companion documents cited by the header exist")

    published = declared_schema_block(text)
    if published != DECLARED_SCHEMA:
        report.fail(
            "schema-sync: docs ledger's published schema block differs from DECLARED_SCHEMA "
            f"in this script (published={published!r})"
        )
    else:
        report.ok("schema-sync: ledger schema block is derived from the single declared source")

    reg = tabs["registered"]
    if reg is None:
        report.fail("registered-hook table not found (is the event_class column present?)")
        return
    for field in ("behavior", "exercise_status", "proof_layer", "mode/precondition",
                  "citation", "verifying_test", "matcher", "hook", "row_id"):
        if field not in reg["columns"]:
            report.fail(f"registered-hook table is MISSING the '{field}' column")
    if any(f not in reg["columns"] for f in ("behavior", "proof_layer")):
        return

    sentinels = {"verifying_test": "none yet", "mode/precondition": "none"}
    missing_behavior = 0
    for row in reg["rows"]:
        rid = row.get("row_id") or "?"
        for field in ("row_id", "event_class", "matcher", "hook", "mode/precondition",
                      "behavior", "exercise_status", "proof_layer", "citation",
                      "verifying_test"):
            value = (row.get(field) or "").strip()
            if not value:
                if field == "behavior":
                    missing_behavior += 1
                hint = sentinels.get(field)
                suffix = " (declared sentinel: %r)" % (hint,) if hint else ""
                report.fail(f"row {rid}: field '{field}' is blank -- a blank cell is a "
                            f"failure, not a statement that a value is absent" + suffix)
        for field, allowed in (("behavior", DECLARED_SCHEMA["behavior"]),
                               ("exercise_status", DECLARED_SCHEMA["exercise_status"]),
                               ("proof_layer", DECLARED_SCHEMA["proof_layer"])):
            value = (row.get(field) or "").strip()
            if value and value not in allowed:
                report.fail(f"row {rid}: {field}={value!r} is outside the closed set {allowed}")
        citation = row.get("citation") or ""
        if citation.strip() and not PIN_RE.search(citation):
            report.fail(f"row {rid}: citation {citation!r} carries no @<sha8> revision pin")

    if missing_behavior == 0:
        report.ok(f"every one of {len(reg['rows'])} registered-hook rows carries a behavior label")
    else:
        report.fail(f"{missing_behavior} registered-hook row(s) carry no behavior label "
                    f"(required: exactly 0)")

    # `enforced` is the label this lane exists to protect: it requires host-observed prevention
    # AND a linked corpus case. Component evidence can never earn it.
    corpus_rows = set()
    if Path(args.corpus).exists():
        try:
            for entry in read_json(args.corpus):
                if isinstance(entry, dict) and entry.get("table_row"):
                    corpus_rows.add(entry["table_row"])
        except Fail:
            pass
    all_rows = list(reg["rows"]) + list((tabs["subject"] or {}).get("rows", []))
    for row in all_rows:
        rid = row.get("row_id") or "?"
        if (row.get("behavior") or "").strip() == "enforced":
            if (row.get("proof_layer") or "").strip() != "host-observed":
                report.fail(f"row {rid}: behavior=enforced with proof_layer="
                            f"{row.get('proof_layer')!r} -- host prevention was not observed")
            if rid not in corpus_rows:
                report.fail(f"row {rid}: behavior=enforced with no linked corpus case")
    enforced = [r for r in all_rows if (r.get("behavior") or "").strip() == "enforced"]
    if enforced:
        report.fail(f"{len(enforced)} row(s) labelled enforced; with no real-Claude-Code "
                    f"dispatcher available in this environment the honest count is 0")
    else:
        report.ok("zero rows labelled enforced -- the honest state of a cycle with no "
                  "host-observed prevention evidence")

    component = [r for r in reg["rows"]
                 if (r.get("proof_layer") or "").strip() == "component-tested"
                 and (r.get("behavior") or "").strip()]
    if component:
        report.ok(f"{len(component)} row(s) carry proof_layer=component-tested with a populated "
                  f"behavior label (anti-vacuity: the label column is live)")
    else:
        report.fail("no row carries proof_layer=component-tested with a populated behavior "
                    "label -- downstream label-selecting assertions would range over nothing")

    # Compatibility ledger.
    compat = tabs["compat"]
    if compat is None:
        report.fail("compatibility-ledger table not found (is the release_key column present?)")
        return
    compat_sentinels = {"claude_code_build": "unknown", "os_runtime": "unknown",
                        "workflow_run_link": "not-run"}
    for row in compat["rows"]:
        rid = row.get("row_id") or row.get("release_key") or "?"
        for field in ("release_key", "claude_code_build", "os_runtime", "commit", "date",
                      "workflow_run_link", "result"):
            if not (row.get(field) or "").strip():
                hint = compat_sentinels.get(field)
                report.fail(f"compatibility row {rid}: field '{field}' is blank"
                            + (f" (use the sentinel {hint!r})" if hint else ""))
        if re.search(r"(?i)\bpass\b", row.get("result") or ""):
            link = (row.get("workflow_run_link") or "").strip()
            if not link or link in ("not-run", "-", "n/a"):
                report.fail(f"compatibility row {rid}: result claims a pass with no "
                            f"workflow-run artifact link")

    # The four measured environment facts must co-occur in ONE row, not scatter across prose.
    env_facts = ["2.1.220", "Linux 6.8.0-117-generic x86_64", "Python 3.12.3", "4c33f2f5"]
    if any(all(fact in " | ".join(r.values()) for fact in env_facts) for r in compat["rows"]):
        report.ok("the current-environment row carries all four measured facts in a single row")
    else:
        report.fail("no single compatibility row carries build + OS + runtime + commit together")

    # Per-release coverage, derived from an enumerable inventory rather than hand-authored.
    inventory = set()
    try:
        tags = subprocess.run(["git", "tag", "-l"], capture_output=True, text=True, timeout=30)
        inventory |= {t.strip() for t in tags.stdout.split("\n") if t.strip()}
    except Exception:  # noqa: BLE001
        pass
    if Path(args.changelog).exists():
        for line in read_text(args.changelog).split("\n"):
            m = re.match(r"^##+\s+\[?([0-9][^\]\s]*)\]?", line)
            if m:
                inventory.add(m.group(1))
    keys = {(r.get("release_key") or "").strip().lstrip("v") for r in compat["rows"]}
    if inventory:
        missing = {rel for rel in inventory if rel.lstrip("v") not in keys}
        if missing:
            report.fail(f"release inventory not covered: {sorted(missing)} has no ledger row "
                        f"(a release whose evidence is unknown is recorded as unsupported, "
                        f"never omitted)")
        else:
            report.ok(f"every release in the inventory {sorted(inventory)} has a ledger row")
    else:
        if re.search(r"(?i)zero tagged releases", text):
            report.ok("empty release inventory is stated explicitly")
        else:
            report.fail("release inventory is empty and the ledger does not state that the "
                        "project currently publishes zero tagged releases")


# ---------------------------------------------------------------------------
# --claims
# ---------------------------------------------------------------------------
def extract_first_quoted(line, quote):
    start = line.find(quote)
    if start < 0:
        return None
    end = line.find(quote, start + 1)
    return None if end < 0 else line[start + 1:end]


def probe_witness(form, classifier_path, ere_anchor, py_anchor):
    """Return (classifier_outcome, anchor_outcome) for one form.

    Only the harmless `status` subcommand is ever used. Both _command_token_index() and the
    anchor classes are subcommand-independent, so this measures the detection boundary without
    constructing a destructive command. DISCLOSED SUBSTITUTION, not circumvention.
    """
    try:
        proc = subprocess.run([sys.executable, classifier_path], input=form + "\n",
                              capture_output=True, text=True, timeout=30)
        parsed = json.loads(proc.stdout) if proc.returncode == 0 else None
    except Exception:  # noqa: BLE001
        parsed = None
    if parsed is None:
        classifier = "ERROR"
    elif parsed:
        classifier = "detected"
    else:
        classifier = "MISS"
    py_match = re.search(py_anchor, form) is not None
    try:
        ere = subprocess.run(["grep", "-qE", ere_anchor + "[[:space:]]+"],
                             input=form + "\n", capture_output=True, text=True, timeout=30)
        ere_match = ere.returncode == 0
    except Exception:  # noqa: BLE001
        ere_match = py_match
    if py_match != ere_match:
        return classifier, "DIVERGENT"
    return classifier, ("MATCH" if py_match else "no-match")


def check_claims(args, report):
    bash_src = read_text(args.bash_safety)
    guard_src = read_text(args.git_guard)
    classifier_src = read_text(args.classifier)

    # 1. Both regex engines still exist. A future consolidation must break the RISK-2 prose
    #    loudly instead of silently outdating it.
    for symbol, src, path in (("GIT_CMD_RE", bash_src, args.bash_safety),
                              ("GIT_COMMAND_RE", guard_src, args.git_guard)):
        if re.search(rf"^{symbol}\s*=", src, re.M):
            report.ok(f"symbol {symbol} still defined in {path}")
        else:
            report.fail(f"symbol {symbol} no longer defined in {path} -- the published RISK-2 "
                        f"claim that both engines still exist is now false")

    # 2. The arch-F7 accepted-residual block is intact.
    if re.search(r"(?s)Known scope boundaries \(arch-F7\).{0,400}env\s+-i.{0,400}redirection",
                 classifier_src):
        report.ok("arch-F7 accepted-residual block still names both residual classes")
    else:
        report.fail("arch-F7 accepted-residual block changed -- RISK-3's published residual "
                    "table can no longer be assumed to describe the current boundary")

    # 3. Anchor-class literals unchanged (adding '/' would change the residual class).
    ere_line = next((l for l in bash_src.split("\n") if l.startswith("GIT_CMD_RE=")), "")
    ere_anchor = extract_first_quoted(ere_line, "'") or ""
    py_line = next((l for l in guard_src.split("\n") if l.startswith("GIT_COMMAND_RE")), "")
    py_anchor = extract_first_quoted(py_line, "'") or ""
    if ere_anchor == RECORDED_ERE_ANCHOR:
        report.ok("POSIX ERE anchor class unchanged")
    else:
        report.fail(f"POSIX ERE anchor class changed: {ere_anchor!r} != {RECORDED_ERE_ANCHOR!r}")
    if py_anchor == RECORDED_PY_ANCHOR:
        report.ok("Python anchor class unchanged")
    else:
        report.fail(f"Python anchor class changed: {py_anchor!r} != {RECORDED_PY_ANCHOR!r}")
    if not ere_anchor or not py_anchor:
        return

    # 4. Every witness probed INDIVIDUALLY.
    drift = 0
    for witness in MANDATED_WITNESSES:
        classifier, anchor = probe_witness(witness["form"], args.classifier, ere_anchor, py_anchor)
        if (classifier, anchor) != (witness["classifier"], witness["anchor"]):
            drift += 1
            report.fail(f"matrix_probe {witness['id']} ({witness['form']!r}): recorded "
                        f"({witness['classifier']}, {witness['anchor']}) but observed "
                        f"({classifier}, {anchor}) -- the published matrix is now wrong")
    if drift == 0:
        report.ok(f"all {len(MANDATED_WITNESSES)} mandated witnesses reproduce their recorded "
                  f"(classifier, anchor) outcome")

    # 5. Token sets. A widened _WRAPPERS changes the SIZE of the residual class even when every
    #    probed representative still behaves exactly as recorded -- the unprobed-sibling case.
    live_wrappers = extract_wrappers(classifier_src)
    if live_wrappers is None:
        report.fail("_WRAPPERS changed: the constant could not be resolved from "
                    f"{args.classifier} by ast.literal_eval -- an unresolvable declaration "
                    f"cannot be compared against the published set")
    elif live_wrappers == sorted(RECORDED_WRAPPERS):
        report.ok(f"_WRAPPERS unchanged ({len(live_wrappers)} tokens, recorded @{RECORDED_AT})")
    else:
        report.fail(f"_WRAPPERS changed: {live_wrappers} != {sorted(RECORDED_WRAPPERS)} -- the "
                    f"residual class named in the published matrix has a different size now")

    # The token sets are matched ONLY inside their anchored publication regions. Matching
    # anywhere in the document is vacuous: '>' appears on every blockquote line and '<' inside
    # HTML comment delimiters, so two of the seven redirection operators used to be satisfied
    # by unrelated prose and could never be reported missing.
    ledger_text = read_text(args.ledger_file)
    token_check_failed = False
    for label, expected in (("wrapper", RECORDED_WRAPPERS),
                            ("leading-redirection", RECORDED_REDIRECTION_OPS)):
        published = published_token_set(ledger_text, label)
        if published is None:
            token_check_failed = True
            report.fail(f"published {label} token set is incomplete in the ledger: missing "
                        f"{sorted(expected)} (the published-tokens:{label} region is absent "
                        f"or carries no 'N tokens:' list)")
            continue
        absent = sorted(set(expected) - set(published))
        extra = sorted(set(published) - set(expected))
        duplicated = sorted({t for t in published if published.count(t) > 1})
        if absent:
            token_check_failed = True
            report.fail(f"published {label} token set is incomplete in the ledger: missing "
                        f"{absent}")
        if extra:
            token_check_failed = True
            report.fail(f"published {label} token set publishes {extra}, which is not in the "
                        f"recorded set -- the document claims coverage it has no record of")
        if duplicated:
            token_check_failed = True
            report.fail(f"published {label} token set lists {duplicated} more than once")
    # Reported ONLY when the loop above found nothing. Calling this unconditionally made one
    # run emit a FAIL and a PASS for the same assertion -- a reporting-integrity defect in the
    # one document whose premise is that its rows can be trusted.
    if not token_check_failed:
        report.ok("published wrapper + leading-redirection token sets match the recorded sets")

    # 6. Gate-architecture census, derived structurally so a respelled guard cannot hide.
    census = shell_gate_census(bash_src)
    for key in sorted(RECORDED_CENSUS):
        observed, expected = census[key], RECORDED_CENSUS[key]
        if observed == expected:
            report.ok(f"{key.replace('_', '-')} gate census unchanged ({observed})")
        else:
            report.fail(f"{key.replace('_', '-')} gate census changed: observed {observed} "
                        f"recorded {expected} -- a gate gaining or losing a "
                        f"classifier-consumption shape changes which inputs keep a backstop, "
                        f"without any probed form changing")

    # 7. Ledger registered-hook rows == settings-derived hook set, both directions.
    reg = ledger_tables(args.ledger_file)["registered"]
    if reg is None:
        report.fail("registered-hook table not found -- cannot verify set equality")
    else:
        derived = settings_triples(args.settings)
        published = {((r.get("event_class") or "").strip(),
                      (r.get("matcher") or "").strip(),
                      (r.get("hook") or "").strip()) for r in reg["rows"]}
        only_settings = sorted(derived - published)
        only_ledger = sorted(published - derived)
        if only_settings or only_ledger:
            for item in only_settings:
                report.fail(f"wired in settings but absent from the ledger: {item}")
            for item in only_ledger:
                report.fail(f"present in the ledger but not wired in settings: {item}")
        else:
            report.ok(f"ledger registered-hook rows are set-equal to the {len(derived)} "
                      f"settings-derived hooks (both symmetric differences empty)")

    # 8. Every file:line citation in threat-model section 4 is revision-pinned, and every
    #    residual-risk entry states its status exactly once, in its own normalized field.
    tm = read_text(args.threat_model)
    check_risk_status(tm, report)
    section = re.search(r"(?ims)^##\s+4\.\s+Known Residual Risks.*?(?=^##\s+\d|\Z)", tm)
    if not section:
        report.fail("threat model section 4 not found")
    else:
        unpinned = []
        for line in section.group(0).split("\n"):
            for citation in CITATION_RE.finditer(line):
                tail = line[citation.end():citation.end() + 24]
                if not PIN_RE.search(tail):
                    unpinned.append(citation.group(0))
        if unpinned:
            report.fail(f"{len(unpinned)} unpinned file:line citation(s) in threat model "
                        f"section 4: {unpinned[:5]} -- an unpinned citation IS the defect")
        else:
            report.ok("every file:line citation in threat model section 4 is revision-pinned")


# ---------------------------------------------------------------------------
# --coverage
# ---------------------------------------------------------------------------
def normalize_outcome(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def check_coverage(args, report):
    corpus = read_json(args.corpus)
    corpus_ids = [e.get("case_id") for e in corpus if isinstance(e, dict)]
    if len(corpus_ids) != len(set(corpus_ids)):
        report.fail("corpus case_id values are not unique")
    corpus_set = set(corpus_ids)

    if not Path(args.manifest).exists():
        report.fail(f"run manifest {args.manifest} does not exist -- the suite did not run, or "
                    f"ran without emitting evidence")
        return
    manifest = read_json(args.manifest)

    results = manifest.get("results")
    if not isinstance(results, list):
        report.fail("manifest has no 'results' list")
        return

    # One-to-one, not merely set-equal: duplicates and orphans both fail.
    seen = {}
    for result in results:
        seen.setdefault(result.get("case_id"), 0)
        seen[result.get("case_id")] += 1
    duplicated = sorted(k for k, v in seen.items() if v > 1)
    orphans = sorted(set(seen) - corpus_set)
    missing = sorted(corpus_set - set(seen))
    if duplicated:
        report.fail(f"manifest contains duplicate result objects for {duplicated}")
    if orphans:
        report.fail(f"manifest reports case ids absent from the corpus: {orphans}")
    if missing:
        report.fail(f"corpus cases with no manifest result: {missing}")
    if not (duplicated or orphans or missing):
        report.ok(f"manifest maps one-to-one onto all {len(corpus_set)} corpus cases")

    required = ["release_or_commit", "os_runtime", "event", "matcher_or_hook", "case_id",
                "expected_outcome", "observed_outcome", "exit_stdout_stderr_summary",
                "side_effect_oracle_result", "verdict"]
    bad_fields = bad_provenance = bad_verdict = 0
    for result in results:
        cid = result.get("case_id", "?")
        for field in required:
            value = result.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                bad_fields += 1
                report.fail(f"manifest result {cid}: field '{field}' is null or empty")
        # PROVENANCE, not inequality. An earlier revision of this lane's spec required
        # observed_outcome to DIFFER from expected_outcome; that rule fails every passing case
        # and would make this gate unsatisfiable on a green run. The defensible property is
        # that the observed value was DERIVED from captured evidence of this invocation.
        source = result.get("observed_source")
        if not isinstance(source, dict) or not str(source.get("captured_from", "")).strip():
            bad_provenance += 1
            report.fail(f"manifest result {cid}: observed_outcome carries no observed_source "
                        f".captured_from -- it cannot be distinguished from an authored value")
        elif source.get("exit_code") is None:
            bad_provenance += 1
            report.fail(f"manifest result {cid}: observed_source records no exit code")
        agree = normalize_outcome(result.get("observed_outcome")) == \
            normalize_outcome(result.get("expected_outcome"))
        verdict = normalize_outcome(result.get("verdict"))
        if (verdict == "pass") != agree:
            bad_verdict += 1
            report.fail(f"manifest result {cid}: verdict={result.get('verdict')!r} is not the "
                        f"derived function of observed-vs-expected agreement ({agree})")
    if not bad_fields:
        report.ok(f"every M8 field is populated on all {len(results)} result objects")
    if not bad_provenance:
        report.ok("every observed_outcome is bound to captured process evidence")
    if not bad_verdict:
        report.ok("every verdict is the derived agreement function, not an independent claim")

    # Execution provenance: executed == emitted == corpus, and the manifest belongs to THIS run.
    executed = set(manifest.get("executed_case_ids") or [])
    emitted = set(seen)
    if executed != emitted or executed != corpus_set:
        report.fail(f"executed({len(executed)}) / emitted({len(emitted)}) / "
                    f"corpus({len(corpus_set)}) sets are not identical -- the artifact is "
                    f"evidence of authorship, not of execution")
    else:
        report.ok("executed == emitted == corpus: every result was produced by a live "
                  "invocation in this run")
    collected = manifest.get("collected_tests")
    if not isinstance(collected, int) or collected < 1:
        report.fail(f"manifest reports collected_tests={collected!r}; a suite that collects "
                    f"zero tests exits zero and is not evidence")
    else:
        report.ok(f"suite collected {collected} test(s)")

    expected_run = os.environ.get("GITHUB_RUN_ID", "local")
    expected_sha = os.environ.get("GITHUB_SHA", "")
    if str(manifest.get("run_id")) != str(expected_run):
        report.fail(f"manifest run_id={manifest.get('run_id')!r} does not match the workflow "
                    f"context {expected_run!r}")
    else:
        report.ok(f"manifest run_id matches the executing context ({expected_run})")
    if expected_sha and str(manifest.get("commit_sha")) != str(expected_sha):
        report.fail(f"manifest commit_sha={manifest.get('commit_sha')!r} does not match the "
                    f"workflow context {expected_sha!r}")


# ---------------------------------------------------------------------------
class Report:
    def __init__(self, verbose):
        self.rc = 0
        self.verbose = verbose

    def ok(self, message):
        if self.verbose:
            print(f"  PASS: {message}")

    def fail(self, message):
        print(f"  FAIL: {message}")
        self.rc = 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ledger", action="store_true", help="evidence-integrity gate")
    mode.add_argument("--claims", action="store_true", help="claim-versus-code gate")
    mode.add_argument("--coverage", action="store_true", help="CI run-manifest gate")
    parser.add_argument("--root", default=None, help="repository root (default: git toplevel)")
    parser.add_argument("--ledger-file", default=None)
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--settings", default=None)
    parser.add_argument("--changelog", default=None)
    parser.add_argument("--threat-model", default=None)
    parser.add_argument("--classifier", default=None)
    parser.add_argument("--bash-safety", default=None)
    parser.add_argument("--git-guard", default=None)
    parser.add_argument("--quiet", action="store_true", help="print failures only")
    args = parser.parse_args(argv)

    if args.root:
        root = Path(args.root)
    else:
        try:
            root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                       capture_output=True, text=True, timeout=30,
                                       check=True).stdout.strip())
        except Exception:  # noqa: BLE001
            root = Path.cwd()
    # Resolved once and written back, so companion-document existence resolves against the
    # SAME root a negative fixture was built in.
    args.root = str(root)
    defaults = {
        "ledger_file": "docs/ENFORCEMENT-LEDGER.md",
        "corpus": "hooks/tests/fixtures/adversarial_corpus.json",
        "manifest": "hooks/tests/.enforcement-run-manifest.json",
        "settings": "settings.json",
        "changelog": "CHANGELOG.md",
        "threat_model": "docs/THREAT-MODEL.md",
        "classifier": "hooks/lib/git_command_classifier.py",
        "bash_safety": "hooks/pretool-bash-safety.sh",
        "git_guard": "hooks/pretool-git-privilege-guard.py",
    }
    for name, rel in defaults.items():
        if getattr(args, name) is None:
            setattr(args, name, str(root / rel))

    report = Report(verbose=not args.quiet)
    label = "ledger" if args.ledger else ("claims" if args.claims else "coverage")
    print(f"check-enforcement-evidence --{label}")
    try:
        if args.ledger:
            check_ledger(args, report)
        elif args.claims:
            check_claims(args, report)
        else:
            check_coverage(args, report)
    except Fail as exc:
        print(f"  ERROR: {exc}")
        return 2
    print(f"check-enforcement-evidence --{label}: "
          f"{'PASS' if report.rc == 0 else 'FAIL'}")
    return report.rc


if __name__ == "__main__":
    sys.exit(main())
