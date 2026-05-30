"""Front-matter + annotation parsers for spec-verify.py (R1.6).

Authoritative grammar: /root/docs/dev/specs/MONOLITH-WRITING-GUIDE.md R6.6.

Extracted into a sidecar module because spec-verify.py would exceed
the 800-line quality-gate limit if these parsers were inlined. The
parent module imports the public API: parse_front_matter,
parse_role_headings, parse_consumers_tags, lookup_role_block. Regex
constants are also re-exported via the spec_verify_parsers namespace.

Parsers are PARSE-ONLY -- they expose structured records that R3.3
and R5.3 consume. Calling them on legacy monoliths (no guide_version)
is safe and cheap; downstream callers apply the guide_version gate
before acting on the output (no-brick invariant, spec Sec 1.4).
"""

import re


HEADING_REGEX = re.compile(
    r"^(?P<hashes>##|###)\s+Role:\s+(?P<agent>[a-z0-9_\-]+)\s*$",
    re.IGNORECASE,
)
CONSUMERS_REGEX = re.compile(
    r"^<!--\s*consumers:\s*(?P<payload>\[[^\]]*\]|all)\s*-->\s*$",
    re.IGNORECASE,
)
CONSUMERS_INLINE_REGEX = re.compile(
    r"^consumers:\s+(?P<payload>\[[^\]]*\]|all)\s*$",
    re.IGNORECASE,
)
_HEADING_PREFIX_RE = re.compile(r"^(#{1,6})(\s|$)")
_FM_FENCE = "---"
_FM_LIST_KEYS = ("required_consumers", "committed_requirement_ids")


def _split_consumers_payload(payload):
    """Normalize a consumers: payload into a list or ['all'] wildcard."""
    stripped = payload.strip()
    if stripped.lower() == "all":
        return ["all"]
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [t.strip().lower() for t in inner.split(",") if t.strip()]
    return []


def _parse_list_value(value):
    """Parse a bracketed list; 1-element fallback for tolerance."""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [tok.strip() for tok in inner.split(",") if tok.strip()]
    return [value] if value else []


def _find_front_matter_end(lines):
    """Return 0-indexed closing-fence line, or -1 if none."""
    if not lines or lines[0].strip() != _FM_FENCE:
        return -1
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM_FENCE:
            return i
    return -1


def _coerce_fm_value(key, value):
    """Coerce a front-matter value based on its key's expected type."""
    if key == "guide_version":
        try:
            return int(value)
        except ValueError:
            return None
    if key in _FM_LIST_KEYS:
        return _parse_list_value(value)
    return value


def _parse_front_matter_kv(raw, result):
    """Parse one key:value line from front matter into ``result``."""
    stripped = raw.strip()
    if not stripped or stripped.startswith("#") or ":" not in stripped:
        return
    key, _, value = stripped.partition(":")
    key = key.strip()
    value = value.strip()
    if not key:
        return
    result[key] = _coerce_fm_value(key, value)


def parse_front_matter(monolith_text):
    """Parse YAML-style front-matter fenced by '---' at the top.

    Returns a dict with possible keys ``guide_version`` (int or None),
    ``required_consumers`` / ``committed_requirement_ids`` (lists).
    Unknown keys pass through as raw strings. Empty dict when no
    front-matter block exists or the block is malformed.
    """
    if not monolith_text:
        return {}
    lines = monolith_text.splitlines()
    end_idx = _find_front_matter_end(lines)
    if end_idx < 0:
        return {}
    result = {}
    for raw in lines[1:end_idx]:
        _parse_front_matter_kv(raw, result)
    return result


def _heading_level(stripped):
    """Return hash-count for a Markdown heading line, else 0."""
    match = _HEADING_PREFIX_RE.match(stripped)
    if not match:
        return 0
    return len(match.group(1))


def _next_heading_line(lines, from_idx, max_level):
    """1-indexed next heading at depth <= max_level, or EOF."""
    for j in range(from_idx + 1, len(lines)):
        level = _heading_level(lines[j].lstrip())
        if level and level <= max_level:
            return j + 1
    return len(lines)


def _record_role_heading(i, match, lines):
    """Build one role-heading record from a regex match at line ``i``."""
    heading_level = len(match.group("hashes"))
    agent = match.group("agent").lower()
    end_line = _next_heading_line(lines, i, heading_level)
    return {
        "agent": agent,
        "line_start": i + 1,
        "line_end": end_line,
        "heading_level": heading_level,
    }


def parse_role_headings(monolith_text):
    """Return role-heading records ('## Role: X' / '### Role: X').

    Each record is {agent, line_start, line_end, heading_level}. The
    block runs from the heading down to (but excluding) the next
    sibling-or-higher heading, or EOF.
    """
    if not monolith_text:
        return []
    lines = monolith_text.splitlines()
    results = []
    for i, raw in enumerate(lines):
        match = HEADING_REGEX.match(raw.rstrip())
        if match:
            results.append(_record_role_heading(i, match, lines))
    return results


def _find_fence_close_index(lines):
    """Return 0-indexed line of the top fence close, or -1."""
    if not lines or lines[0].strip() != _FM_FENCE:
        return -1
    for j in range(1, len(lines)):
        if lines[j].strip() == _FM_FENCE:
            return j
    return -1


def _front_matter_line_set(lines):
    """Return 0-indexed line numbers inside the top fence."""
    close_idx = _find_fence_close_index(lines)
    if close_idx < 0:
        return set()
    return set(range(0, close_idx + 1))


def _match_consumers_line(stripped, i, in_fm):
    """Return (payload, format) if line is a consumers annotation."""
    html_match = CONSUMERS_REGEX.match(stripped)
    if html_match:
        return html_match.group("payload"), "html_comment"
    if i in in_fm:
        return None
    inline_match = CONSUMERS_INLINE_REGEX.match(stripped)
    if inline_match:
        return inline_match.group("payload"), "yaml_inline"
    return None


def _find_consumers_hits(lines):
    """Return [(idx, payload, format)] for each annotation line."""
    in_fm = _front_matter_line_set(lines)
    hits = []
    for i, raw in enumerate(lines):
        hit = _match_consumers_line(raw.rstrip(), i, in_fm)
        if hit is not None:
            payload, fmt = hit
            hits.append((i, payload, fmt))
    return hits


def _find_next_heading_any_level(lines, from_idx):
    """0-indexed line of next heading at any level, or len(lines)."""
    for j in range(from_idx, len(lines)):
        if _heading_level(lines[j].lstrip()):
            return j
    return len(lines)


def _consumers_block_span(idx, lines, next_ann_idx):
    """Compute (block_start, block_end) 1-indexed for annotation idx."""
    block_start_idx = idx + 1
    terminator = _find_next_heading_any_level(lines, block_start_idx)
    if next_ann_idx is not None:
        terminator = min(terminator, next_ann_idx)
    if block_start_idx >= len(lines):
        return len(lines), len(lines)
    block_start = block_start_idx + 1
    if terminator > block_start_idx:
        block_end = terminator
    else:
        block_end = block_start_idx + 1
    return block_start, block_end


def _build_consumers_record(idx, payload, fmt, lines, next_ann_idx):
    """Build one consumers-tag record with its governed block span."""
    block_start, block_end = _consumers_block_span(idx, lines, next_ann_idx)
    return {
        "consumers": _split_consumers_payload(payload),
        "line": idx + 1,
        "format": fmt,
        "block_start": block_start,
        "block_end": block_end,
    }


def parse_consumers_tags(monolith_text):
    """Return consumers: annotation records with governed block spans.

    Recognizes both HTML-comment and inline-YAML forms. Inline-YAML
    matches inside the top front-matter fence are ignored (documented
    limitation -- treated as front-matter keys instead).
    """
    if not monolith_text:
        return []
    lines = monolith_text.splitlines()
    raw_hits = _find_consumers_hits(lines)
    if not raw_hits:
        return []
    results = []
    for k, (idx, payload, fmt) in enumerate(raw_hits):
        next_ann = None
        if k + 1 < len(raw_hits):
            next_ann = raw_hits[k + 1][0]
        record = _build_consumers_record(idx, payload, fmt, lines, next_ann)
        results.append(record)
    return results


def _role_heading_candidate(rh, target):
    """Return a candidate dict from a role-heading record."""
    return {
        "line_start": rh["line_start"],
        "line_end": rh["line_end"],
        "source_annotation": "role_heading",
        "agent": target,
    }


def _consumers_tag_candidate(tag, target):
    """Return a candidate dict from a consumers-tag record."""
    return {
        "line_start": tag["block_start"],
        "line_end": tag["block_end"],
        "source_annotation": "consumers_tag",
        "agent": target,
    }


def _role_heading_candidates(role_headings, target):
    """Candidates from role-heading records matching ``target``."""
    out = []
    for rh in role_headings:
        if rh["agent"] == target:
            out.append(_role_heading_candidate(rh, target))
    return out


def _consumers_tag_matches(tag, target):
    """True if consumers-tag record provides role-evidence for target."""
    consumers = tag["consumers"]
    return "all" in consumers or target in consumers


def _consumers_tag_candidates(consumers_tags, target):
    """Candidates from consumers-tag records matching ``target``."""
    out = []
    for tag in consumers_tags:
        if _consumers_tag_matches(tag, target):
            out.append(_consumers_tag_candidate(tag, target))
    return out


def lookup_role_block(
    monolith_text, agent, role_headings=None, consumers_tags=None,
):
    """First block providing role-evidence for ``agent``, or None.

    Annotation Type 1 (Role heading) and Annotation Type 2 (consumers
    tag) are equal-priority; the earlier in file order wins.
    """
    if not monolith_text:
        return None
    if role_headings is None:
        role_headings = parse_role_headings(monolith_text)
    if consumers_tags is None:
        consumers_tags = parse_consumers_tags(monolith_text)
    target = agent.lower()
    candidates = _role_heading_candidates(role_headings, target)
    candidates += _consumers_tag_candidates(consumers_tags, target)
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["line_start"])
    return candidates[0]
