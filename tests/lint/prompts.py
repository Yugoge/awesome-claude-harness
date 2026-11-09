"""The four prompt checks: hook strength, dead references, repeated blocks, emphasis."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .tree import Finding, Tree

# ---------------------------------------------------------------- shared text helpers


def paragraphs(text: str):
    """(first line number, paragraph text) for each run of non-blank lines."""
    start, buf = None, []
    for n, line in enumerate(text.split("\n"), 1):
        if line.strip():
            if start is None:
                start = n
            buf.append(line)
        elif buf:
            yield start, "\n".join(buf)
            start, buf = None, []
    if buf:
        yield start, "\n".join(buf)


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*(\[<\"'])")


def sentences(text: str):
    """(line number, sentence) for each sentence of each paragraph."""
    for start, para in paragraphs(text):
        pos = 0
        for m in list(SENTENCE_END.finditer(para)) + [None]:
            end = m.start() if m else len(para)
            sent = para[pos:end]
            if sent.strip():
                yield start + para.count("\n", 0, pos), sent
            pos = m.end() if m else len(para)


def strip_code(text: str) -> str:
    """The text with inline code spans and fenced blocks that carry a language tag blanked out
    (line count kept): a literal or a block of code or data is not prose. An untagged fence
    stays, since the commands' dispatch templates are prose sent to a subagent."""
    out, fence = [], None
    for line in text.split("\n"):
        m = re.match(r"\s*(```+|~~~+)\s*(\S*)", line)
        if m:
            fence = (m.group(2) or "") if fence is None else None
            out.append("")
            continue
        if fence:
            out.append("")
            continue
        out.append(re.sub(r"`[^`\n]*`", "", line))
    return "\n".join(out)


# ---------------------------------------------------------------- 1. hook strength

# What the ledger's mode/precondition cell says a hook does by default.
_DEFAULT_BLOCKS = re.compile(r"\bblocking when \S+ is unset \(the default\)", re.I)
_DEFAULT_WARNS = re.compile(r"\b(?:advisory|logs? only|warn(?:s|ing)?(?:[- ]only)?) when \S+ is unset \(the default\)", re.I)
_DEFAULT_OFF = re.compile(r"\b(?:off|disabled|skipped|inactive) (?:by default|when \S+ is unset \(the default\))|\bopt-in\b"
                          r"|\bdefault[- ]off\b", re.I)
_NEVER_BLOCKS = re.compile(r"\bnever blocks?\b|\bexits 0 on every path\b|\bwitness only\b|\bobservational\b"
                           r"|\bwarn(?:s|ing)?[- ]only\b|\bnon-blocking\b", re.I)
_CAN_BLOCK = re.compile(r"\bexits? 2\b|\bblocks?\b|\bblocking\b|\bdenies\b|\brejects\b", re.I)
_QUALIFIED = re.compile(r"\bonly under\b|\bunder \S*=", re.I)
_SWITCH = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")


def ledger_strength(mode: str) -> str:
    """blocks | warns | off | unknown: the hook's default strength as its ledger cell states it.

    "blocks" when a clause says it blocks by default or exits 2 without "only under X=";
    "off" when it says it is off by default; "warns" when it says advisory by default,
    never blocks, warn-only or exits 0 on every path; "unknown" otherwise (`none`)."""
    mode = mode or ""
    if _DEFAULT_BLOCKS.search(mode):
        return "blocks"
    if _DEFAULT_OFF.search(mode):
        return "off"
    if _DEFAULT_WARNS.search(mode):
        return "warns"
    if _NEVER_BLOCKS.search(mode):
        return "warns"
    for clause in re.split(r"[;:]|\.\s", mode):
        if _CAN_BLOCK.search(clause) and not _QUALIFIED.search(clause) and not _NEVER_BLOCKS.search(clause) \
                and not re.search(r"\bnever\b|\bnot\b", clause, re.I):
            return "blocks"
    return "unknown"


def ledger_switches(mode: str) -> set[str]:
    """The environment variables a ledger cell names: the switches that change a default."""
    return set(_SWITCH.findall(mode or ""))


HOOK_MENTION = re.compile(r"(?<![\w.-])(?:[\w./${}:~-]*/)?([a-z0-9][a-z0-9_-]*\.(?:py|sh))(?![\w-])")
_CLAIM = re.compile(r"\b(block|blocks|blocked|blocking|rejects?|rejected|rejecting|den(?:y|ies|ied)|refuses?|refused"
                    r"|exits?\s+(?:with\s+)?(?:code\s+)?2|exit\s+code\s+2|\(exit\s*2\))(?![\w-])", re.I)
_NEGATION = re.compile(r"(?:\b(?:not|never|no|cannot|without|nothing|neither|nor)\b|n't\b|\bnon-)\W*(?:\w+\W+){0,3}$", re.I)
# "it blocks nothing", "it blocks no Write": the negation follows the verb
_NEGATED_OBJECT = re.compile(r"\s+(?:no|nothing|none|neither|never|not)\b", re.I)
# "block" as a verb needs a modal or "to" in front of it; elsewhere it is the noun
_VERB_LEAD = {"to", "will", "would", "can", "may", "might", "could", "should", "must", "does", "do", "then", "and", "or"}
_NOUN_LEAD = {"obligation", "code", "fenced", "response", "bash", "json", "yaml", "markdown", "template", "shared",
              "these", "those", "the", "two", "three", "several", "multiple", "all", "such", "text", "context"}
_PRONOUN = re.compile(r"^\W*(?:it|this hook|the hook|that hook|this gate|the gate)\b", re.I)


def _claims(sent: str):
    """The blocking claims in a sentence: (match) for each verb not negated and not a noun."""
    for m in _CLAIM.finditer(sent):
        word = m.group(1).lower()
        before = sent[: m.start()]
        prev = re.findall(r"[\w-]+", before[-40:])
        lead = prev[-1].lower() if prev else ""
        if _NEGATION.search(before[-60:]) or _NEGATED_OBJECT.match(sent[m.end():]):
            continue
        if word == "block" and lead not in _VERB_LEAD:
            continue
        if word == "blocks" and lead in _NOUN_LEAD:
            continue
        if word in ("deny",) and re.match(r"\W*(?:list|lists|rule|rules|entr|pattern)", sent[m.end():], re.I):
            continue
        yield m


def check_hook_strength(tree: Tree) -> list[Finding]:
    rows = {}
    for r in tree.ledger_rows:
        rows.setdefault(r.get("hook", ""), r)
    out = []
    for rel in tree.prompts:
        prev_hooks: list[str] = []
        for line, sent in sentences(tree.read(rel)):
            mentions = [m for m in HOOK_MENTION.finditer(sent) if m.group(1) in tree.hook_names]
            claimed: dict[str, list] = {}
            for claim in _claims(sent):
                before = [m for m in mentions if m.start() < claim.start()]
                after = [m for m in mentions if m.start() >= claim.start()]
                if before:
                    hook = before[-1].group(1)
                elif after:
                    hook = after[0].group(1)
                elif len(set(prev_hooks)) == 1 and _PRONOUN.match(sent):
                    hook = prev_hooks[0]
                else:
                    continue
                claimed.setdefault(hook, []).append(claim)
            for hook, claims in claimed.items():
                row = rows.get(hook)
                if not row:
                    continue
                mode = row.get("mode/precondition", "")
                strength = ledger_strength(mode)
                if strength not in ("warns", "off"):
                    continue
                if any(s in sent for s in ledger_switches(mode)):
                    continue        # the sentence states the condition under which it blocks
                said = "only warns" if strength == "warns" else "is off"
                words = ", ".join(repr(c.group(1)) for c in claims)
                out.append(Finding("hook-strength", rel, line + sent.count("\n", 0, claims[0].start()),
                                   f"says {hook} blocks ({words}); ledger row {row.get('row_id', '?')} says by "
                                   f"default it {said}: {mode[:140]}"))
            prev_hooks = [m.group(1) for m in mentions]
    return out


# ---------------------------------------------------------------- 2. dead references

# A reference anchored at the harness home names a file of this tree. A relative reference
# does so when it starts at a directory only the harness has; scripts/, docs/ and tests/
# are left out because a product repository has its own.
_HOME = (r"(?:(?:~|\$HOME|\$\{HOME\}|\"\$HOME\"|\"\$\{HOME\}\"|/roo[t]|/home/[^/\s`'\"]+|/Users/[^/\s`'\"]+)/\.claude/"
         r"|\"?\$\{CLAUDE_HOME(?::-[^}\s]*)?\}\"?/|\"?\$CLAUDE_HOME\"?/)")
_SEG = r"[A-Za-z0-9_.-]+"
_ANCHORED = re.compile(_HOME + r"(" + _SEG + r"(?:/" + _SEG + r")*/?)")
HARNESS_DIRS = ("hooks", "commands", "agents", "schemas", "policies", "skills")
_RELATIVE = re.compile(r"(?<![\w./$~{}<>*@:-])((?:" + "|".join(HARNESS_DIRS) + r")/" + _SEG + r"(?:/" + _SEG + r")*/?)")
_FILE_EXT = {"py", "sh", "md", "json", "jsonl", "yml", "yaml", "txt", "toml", "ini", "cfg", "ts", "js", "mjs", "cjs",
             "html", "css", "ere", "service", "lock", "log", "sqlite3", "flag", "tmp", "bak", "csv", "tsv", "xml", "svg",
             "png", "pid", "bash"}
_PLACEHOLDER_NEXT = set("<{*$[")


def _resolves(tree: Tree, rel: str) -> bool:
    if tree.exists(rel):
        return True
    stem, dot, ext = rel.rsplit("/", 1)[-1].rpartition(".")
    if not dot or not stem:             # named without its suffix: a module or a script
        return any(tree.exists(rel + e) for e in (".py", ".sh", ".md", ".json"))
    if ext not in _FILE_EXT:            # module.attribute: hooks/lib/x.function
        return _resolves(tree, rel.rsplit(".", 1)[0])
    return False


def references(text: str):
    """(line, tree-relative path) for every harness file reference in a prompt's text."""
    for n, line in enumerate(text.split("\n"), 1):
        spans = []
        for rx in (_ANCHORED, _RELATIVE):
            for m in rx.finditer(line):
                if any(a <= m.start(1) < b for a, b in spans):
                    continue
                spans.append((m.start(), m.end()))
                path = m.group(1)
                nxt = line[m.end(1): m.end(1) + 1]
                if nxt in _PLACEHOLDER_NEXT or "..." in path:
                    continue
                path = path.rstrip(".,:;)]'\"`").rstrip("/")
                if path and not path.startswith("."):
                    yield n, path


def check_dead_references(tree: Tree) -> list[Finding]:
    found = []
    for rel in tree.prompts:
        for line, path in references(tree.read(rel)):
            if not _resolves(tree, path):
                found.append((rel, line, path))
    # a directory git ignores (venv/, logs/*) is ignored for every path under it
    probes = {p: (p, p + "/", p + "/.probe") for p in {p for _, _, p in found}}
    ignored = tree.ignored(sorted({q for qs in probes.values() for q in qs}))
    return [Finding("dead-reference", rel, line, f"names {path}, which is not in the tree "
                    f"(write an example with a placeholder, e.g. <name>)")
            for rel, line, path in found if not ignored.intersection(probes[path])]


# ---------------------------------------------------------------- 3. repeated blocks

BLOCK_LINES = 10


def _content_lines(text: str) -> list[tuple[int, str]]:
    """(line number, whitespace-normalized line) for each line holding a letter or digit."""
    return [(n, re.sub(r"\s+", " ", line.strip())) for n, line in enumerate(text.split("\n"), 1)
            if re.search(r"[A-Za-z0-9]", line)]


def check_repeated_blocks(tree: Tree, size: int = BLOCK_LINES) -> list[Finding]:
    windows: dict[str, list] = {}
    where: dict[str, set] = defaultdict(set)
    for rel in tree.prompts:
        lines = _content_lines(tree.read(rel))
        ws = []
        for i in range(len(lines) - size + 1):
            h = hashlib.sha1("\n".join(text for _, text in lines[i: i + size]).encode()).hexdigest()
            ws.append((lines[i][0], lines[i + size - 1][0], h))
            where[h].add(rel)
        windows[rel] = ws
    out = []
    for rel in tree.prompts:
        run = None
        for i, (first, last, h) in enumerate(windows[rel] + [(0, 0, None)]):
            others = where[h] - {rel} if h else set()
            if others and run and i == run["end"] + 1:
                run.update(end=i, last=last, others=run["others"] | others)
                continue
            if run:
                n = run["end"] - run["start"] + size
                out.append(Finding("repeated-block", rel, run["first"],
                                   f"lines {run['first']}-{run['last']} ({n} content lines) are repeated in "
                                   + ", ".join(sorted(run["others"]))))
                run = None
            if others:
                run = {"start": i, "end": i, "first": first, "last": last, "others": others}
    return out


# ---------------------------------------------------------------- 4. emphasis

EMPHASIS = re.compile(r"\b(?:CRITICAL|MANDATORY|NON-NEGOTIABLE|HARD RULES?|PARAMOUNT)\b")
EMPHASIS_LIMIT = 3


def check_emphasis(tree: Tree, limit: int = EMPHASIS_LIMIT) -> list[Finding]:
    out = []
    for rel in tree.prompts:
        hits = [(n, m.group(0)) for n, line in enumerate(strip_code(tree.read(rel)).split("\n"), 1)
                for m in EMPHASIS.finditer(line)]
        if len(hits) > limit:
            out.append(Finding("emphasis", rel, hits[0][0], f"{len(hits)} emphasis words (at most {limit}): "
                               + ", ".join(f"{w} :{n}" for n, w in hits[:12]) + (" ..." if len(hits) > 12 else "")))
    return out
