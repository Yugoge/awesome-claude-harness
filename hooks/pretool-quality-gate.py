#!/usr/bin/env python3
"""
PreToolUse Hook: Quality gate for Write/Edit operations (advisory).

Warns the model (PreToolUse additionalContext JSON on stdout, which the CLI adds
to its context beside the tool result; the call is never refused) when a Write's
content, or an Edit's result, violates a quantified quality threshold:
- File length: max 800 lines
- Function length: max 30 lines
- Nesting depth: max 3 levels

Option alpha (no-net-worsening): if post-edit content has violations, the hook
ALSO computes pre-edit metrics. Edits that do not worsen per-function-name
length or max nesting (file lines are not compared) get no warning. New files (no pre-state) and
previously-compliant files are still measured against the thresholds.

Comparators are symmetric (post <= pre). Per-function comparison is name-keyed
so an edit that shrinks A by 10 while growing B by 10 still warns (B grew).

Hook type: PreToolUse (Write|Edit|MultiEdit matcher; a MultiEdit is not
checked). Exit code: always 0.
"""

import json
import re
import sys
from pathlib import Path

MAX_FILE_LINES = 800
MAX_FUNC_LINES = 30
MAX_NESTING = 3

EXEMPT_PATHS = {
    "node_modules", ".git", "__pycache__", "vendor", "dist", "build",
    ".next", "coverage", ".venv", "venv", "package-lock.json",
    "yarn.lock", "pnpm-lock.yaml",
}
CHECKABLE_EXTS = {".py", ".ts", ".js", ".tsx", ".jsx"}


def is_exempt(file_path):
    """Check if file is exempt from quality checks."""
    parts = Path(file_path).parts
    for part in parts:
        if part in EXEMPT_PATHS:
            return True
    return Path(file_path).suffix not in CHECKABLE_EXTS


def apply_edit_replace(current, tool_input):
    """Apply an Edit's old_string/new_string replacement to current content."""
    old = tool_input.get("old_string", "")
    new = tool_input.get("new_string", "")
    if not old or old not in current:
        return current
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def get_final_content(data):
    """Get the content that would result from this operation."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if tool_name == "Write":
        return tool_input.get("content", ""), file_path
    if tool_name != "Edit":
        return "", file_path
    try:
        current = Path(file_path).read_text()
    except Exception:
        return "", file_path
    return apply_edit_replace(current, tool_input), file_path


def check_file_length(lines):
    """Check if file exceeds max line count."""
    if len(lines) <= MAX_FILE_LINES:
        return []
    msg = "File has %d lines (max %d). Split into modules." % (len(lines), MAX_FILE_LINES)
    return [msg]


def _record_python_func(funcs, name, start, length):
    """Append a (name, start_line_1based, length) tuple."""
    funcs.append((name, start + 1, length))


def _is_python_func_end(stripped, indent, func_indent):
    """True iff this line marks end of the currently-tracked python function."""
    if not stripped:
        return False
    if indent > func_indent:
        return False
    return not stripped.startswith("#") and not stripped.startswith("@")


def _start_python_func(line, stripped):
    """Parse a def line; return (name, indent) or None."""
    is_def = stripped.startswith("def ") or stripped.startswith("async def ")
    if not is_def:
        return None
    m = re.search(r"(?:async\s+)?def\s+(\w+)", stripped)
    name = m.group(1) if m else "?"
    indent = len(line) - len(stripped)
    return name, indent


def _close_python_func(funcs, fname, fs, end):
    """Record a closed function and return -1 to clear tracking state."""
    if fs >= 0:
        _record_python_func(funcs, fname, fs, end - fs)
    return -1


def iter_python_functions(lines):
    """Return list of (name, start_1based, length) for every python function."""
    funcs = []
    fs, fname, find = -1, "", 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        new_func = _start_python_func(line, stripped)
        if new_func is not None:
            fs = _close_python_func(funcs, fname, fs, i)
            fname, find = new_func
            fs = i
            continue
        if fs >= 0 and _is_python_func_end(stripped, indent, find):
            fs = _close_python_func(funcs, fname, fs, i)
    _close_python_func(funcs, fname, fs, len(lines))
    return funcs


def check_function_length_python(lines):
    """Report Python functions exceeding MAX_FUNC_LINES."""
    out = []
    for name, start_line, length in iter_python_functions(lines):
        if length > MAX_FUNC_LINES:
            msg = "Function `%s` (line %d) is %d lines (max %d)"
            out.append(msg % (name, start_line, length, MAX_FUNC_LINES))
    return out


def _ts_func_pattern():
    """Compiled function-detection regex for TS/JS."""
    pat = (r"(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)"
           r"|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("
           r"|(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{)")
    return re.compile(pat)


def _ts_brace_step(ch, bc, started):
    """Update brace counter for one character; return (bc, started)."""
    if ch == "{":
        return bc + 1, True
    if ch == "}":
        return bc - 1, started
    return bc, started


def _scan_ts_func_body(lines, start):
    """Scan from `start` until braces balance; return inclusive end-line index."""
    bc, started = 0, False
    for j in range(start, len(lines)):
        for ch in lines[j]:
            bc, started = _ts_brace_step(ch, bc, started)
        if started and bc == 0:
            return j
    return len(lines) - 1


def iter_ts_functions(lines):
    """Return list of (name, start_1based, length) for every TS/JS function."""
    pat = _ts_func_pattern()
    funcs = []
    i = 0
    while i < len(lines):
        m = pat.search(lines[i])
        if m:
            name = m.group(1) or m.group(2) or m.group(3) or "?"
            end = _scan_ts_func_body(lines, i)
            funcs.append((name, i + 1, end - i + 1))
            i = end
        i += 1
    return funcs


def check_function_length_ts(lines):
    """Report TS/JS functions exceeding MAX_FUNC_LINES."""
    out = []
    for name, start_line, length in iter_ts_functions(lines):
        if length > MAX_FUNC_LINES:
            msg = "Function `%s` (line %d) is %d lines (max %d)"
            out.append(msg % (name, start_line, length, MAX_FUNC_LINES))
    return out


def _py_nest_record(line, stripped, in_paren, md, ml, i):
    """Record python nesting depth for one non-continuation line."""
    if in_paren > 0:
        return md, ml
    indent = len(line) - len(stripped)
    depth = indent // 4
    if depth > md:
        return depth, i + 1
    return md, ml


def _max_nesting_py(lines):
    """Return (max_depth, line_1based) from python indentation, ignoring continuations."""
    md, ml, in_paren = 0, 0, 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        is_blank_or_comment = not stripped or stripped.startswith("#")
        if not is_blank_or_comment:
            md, ml = _py_nest_record(line, stripped, in_paren, md, ml, i)
        in_paren += line.count("(") - line.count(")")
        if in_paren < 0:
            in_paren = 0
    return md, ml


def _ts_open_brace(depth, max_depth, max_line, line_idx):
    """Handle a `{` token; return (depth, max_depth, max_line)."""
    depth += 1
    if depth > max_depth:
        return depth, depth, line_idx + 1
    return depth, max_depth, max_line


def _max_nesting_ts_step(line, depth, max_depth, max_line, line_idx):
    """Process one TS/JS line; return (new_depth, new_max_depth, new_max_line)."""
    for ch in line:
        if ch == "{":
            depth, max_depth, max_line = _ts_open_brace(depth, max_depth, max_line, line_idx)
        elif ch == "}":
            depth -= 1
    return depth, max_depth, max_line


def _max_nesting_ts(lines):
    """Return (effective_max_depth, line_1based) from TS/JS brace tracking."""
    md, ml, depth = 0, 0, 0
    for i, line in enumerate(lines):
        depth, md, ml = _max_nesting_ts_step(line, depth, md, ml, i)
    return max(md - 1, 0), ml


def check_nesting_depth(lines, ext):
    """Report a single violation if max nesting exceeds MAX_NESTING."""
    if ext == ".py":
        depth, line = _max_nesting_py(lines)
    else:
        depth, line = _max_nesting_ts(lines)
    if depth <= MAX_NESTING:
        return []
    msg = "Line %d: nesting depth %d (max %d). Extract to helper function."
    return [msg % (line, depth, MAX_NESTING)]


def _functions_for_ext(lines, ext):
    """Return per-function list and max-nesting for the given extension."""
    if ext == ".py":
        return iter_python_functions(lines), _max_nesting_py(lines)[0]
    if ext in (".ts", ".js", ".tsx", ".jsx"):
        return iter_ts_functions(lines), _max_nesting_ts(lines)[0]
    return [], 0


def compute_metrics(content, ext):
    """Compute structured metrics: file_lines, per-function lengths, max_nesting."""
    lines = content.split("\n")
    funcs, nesting = _functions_for_ext(lines, ext)
    per = {}
    for name, _, length in funcs:
        if name not in per or length > per[name]:
            per[name] = length
    return {"file_lines": len(lines), "per_function_lines": per, "max_nesting": nesting}


def get_pre_content(data):
    """Read the pre-edit content from disk; return None when no pre-state exists."""
    fp = data.get("tool_input", {}).get("file_path", "")
    if not fp:
        return None
    try:
        return Path(fp).read_text()
    except Exception:
        return None


def _check_func_worsened(pre_funcs, post_funcs):
    """Return (False, reason) on first per-function regression, else (True, '')."""
    for name in set(pre_funcs) | set(post_funcs):
        post_len = post_funcs.get(name, 0)
        if name in pre_funcs and post_len > pre_funcs[name]:
            r = "Function '%s' grew from %d to %d lines"
            return False, r % (name, pre_funcs[name], post_len)
        if name not in pre_funcs and post_len > MAX_FUNC_LINES:
            r = "New function '%s' is %d lines (max %d)"
            return False, r % (name, post_len, MAX_FUNC_LINES)
    return True, ""


def metric_did_not_worsen(pre, post):
    """Return (True, '') if no metric worsened, else (False, reason).

    NOTE: file_lines NOT compared - grandfathering allows legacy file growth
    as long as no per-function metric or nesting depth worsens. Rationale:
    file_lines is the weakest quality signal; the user's M6 goal (unblock
    logger.info-style instrumentation in legacy files) requires this
    relaxation. Per-function and nesting metrics still protect the actual
    quality intent.
    """
    pf, qf = pre.get("per_function_lines", {}), post.get("per_function_lines", {})
    ok, reason = _check_func_worsened(pf, qf)
    if not ok:
        return False, reason
    if post["max_nesting"] > pre["max_nesting"]:
        r = "max nesting went from %d to %d"
        return False, r % (pre["max_nesting"], post["max_nesting"])
    return True, ""


def collect_violations(content, ext):
    """Run all three checks against post-edit content and return violations."""
    lines = content.split("\n")
    out = []
    out.extend(check_file_length(lines))
    if ext == ".py":
        out.extend(check_function_length_python(lines))
    elif ext in (".ts", ".js", ".tsx", ".jsx"):
        out.extend(check_function_length_ts(lines))
    out.extend(check_nesting_depth(lines, ext))
    return out


def emit_violations(file_path, violations):
    """Tell the model (warn-only per user policy: no text-smell hard-blocks)."""
    text = "\n".join(["QUALITY GATE WARNING \u2014 %s:" % file_path]
                     + ["  - %s" % v for v in violations]
                     + ["Quality gate warns (advisory only, not blocking). Consider splitting large functions."])
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                        "additionalContext": text}}))


def _grandfather_or_block(data, file_path, ext, post_content, violations):
    """Decide whether to allow (grandfathered) or warn; always returns 0 (warn-only)."""
    pre_content = get_pre_content(data)
    if pre_content is None:
        emit_violations(file_path, violations)
        return 0
    pre_m = compute_metrics(pre_content, ext)
    post_m = compute_metrics(post_content, ext)
    ok, reason = metric_did_not_worsen(pre_m, post_m)
    if ok:  # grandfathered: pre-existing violations preserved, no metric worsened
        return 0
    emit_violations(file_path, violations + ["Worsened: " + reason])
    return 0


def main():
    """Entry point: read stdin JSON, run quality checks, warn; exit 0."""
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            sys.exit(0)
        post_content, file_path = get_final_content(data)
        if not post_content or not file_path or is_exempt(file_path):
            sys.exit(0)
        ext = Path(file_path).suffix
        violations = collect_violations(post_content, ext)
        if not violations:
            sys.exit(0)
        sys.exit(_grandfather_or_block(data, file_path, ext, post_content, violations))
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
