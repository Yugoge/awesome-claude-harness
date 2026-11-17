#!/usr/bin/env python3
"""Which existing files a Write may replace wholesale (OB-L46): scratch, temp, untracked output.

The overwrite rule (lib/write_gate/overwrite.py) refuses a Write onto an existing file; this
module is its one exemption, an owner decision (F05; CRITIQUE A5: architect, product-owner,
changelog-analyst, push-analyst, merge-analyst, graphify and user have Write but no Edit, so a
refused second Write to their own output was a dead end). overwrite_exempt() answers True only
when every check below passes; any doubt (an unresolvable path, git missing or slow) is False.

Protected, whatever else holds (judged on every view of the path: as written, normalised
without following links; the parent's realpath plus the entry; and the full realpath):

  * harness state (lib/harness_temp_state.classify): every control location in any view, and
    in the realpath every scratch location but the agent scratch ones (claude-scratch,
    codex-outputs, the graphify cache); the rest are written and read back by harness
    processes;
  * another session's scratch: a directory below a temp or name root whose .owner record
    names a different session;
  * a gate-read artifact (is_gate_read_artifact, case folded): anything below
    tests/generated/, tests/reports/, tests/scripts/ or tests/instructions/, and anything
    below docs/dev/, docs/clean/ or docs/test/ except a top-level markdown draft whose name
    carries none of GATE_READ_PREFIXES. Every artifact path a command or agent
    declares in an obligation, and every templated artifact name a command, hook or step
    script refers to, falls inside it: hooks/tests/test_write_gate_overwrite_exempt.py
    scans for them, so a new declared artifact cannot fall outside the set silently;
  * a `.claude` or `.git` component (case folded) outside a project's `.claude/scratch/`
    directory, and the harness home (lib/claude_home.py), its own .claude/scratch/ included;
  * a file with more than one hard link (a link in temp to a tracked file would otherwise
    pass as a temp file);
  * a file ANY enclosing work tree tracks, in its index or its HEAD (literal pathspec), and
    any file git cannot answer for. The work trees are found by walking up from the file to
    every directory holding a .git entry (never by asking git, whose core.worktree, core.bare
    or GIT_* settings could point elsewhere), and git runs on each with an explicit git dir
    and work tree, no system or global config. A .git file counts only as a linked
    worktree whose git dir links back to it; a symlinked .git, a submodule's .git file or
    one swapped to point at another repository is doubt.

Exempt, once nothing above holds, when the realpath is:

  * scratch: an agent scratch location, this session's own scratch dir (<root>/<session_id>/
    with an .owner naming it, root being $TMPDIR, /var/tmp/claude-scratch or a name root's
    claude-scratch/, the roots hooks/session-scratch-init.sh uses), or a `.claude/scratch/`
    directory;
  * temp: below a temp root (harness_temp_state.temp_roots), and, inside a git work tree,
    with no dot-named component below its top;
  * untracked generated output: in a git work tree, not in the index (ignored or not: the
    harness ignores docs/*/), with no dot-named component below the work tree's top (so
    .env and .vscode/... stay protected).

Own output versus gate-read artifact: the line is the reader, not the writer. A draft no gate,
command or step script reads (a role's /tmp/claude-scratch/<role>/ or docs/codex/ notes,
build/out.txt, or docs/dev/arch-probe.md for an actor tool-policy lets write docs/dev/) may be
replaced; a report, context, ticket, manifest, grant or spec that a later gate trusts keeps the
Edit-only rule even when untracked, so a Write-only role writes it once, complete.

Known limits: an artifact a dispatch's obligation declares at a path no command template uses
(the producer-stop gate reads any declared path) is protected only if it lies under an
artifact root or is tracked; a file below a submodule's .git file is never exempt; a
project's moved-away .git dir leaves no index to ask.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LIB = os.path.join(_HOOKS_DIR, "lib")

# Directories whose files gates, commands and step scripts read as evidence. In the first set
# a top-level markdown draft outside GATE_READ_PREFIXES is no artifact; in the second every
# file is (generated tests and manifests, /test's reports, validators and instructions).
ARTIFACT_ROOTS = (("docs", "dev"), ("docs", "clean"), ("docs", "test"))
WHOLE_ARTIFACT_ROOTS = (("tests", "generated"), ("tests", "reports"), ("tests", "scripts"),
                        ("tests", "instructions"))
# Name families of the artifacts read there (every templated name the harness refers to).
GATE_READ_PREFIXES = (
    "acceptance-criteria-", "ba-panel-", "ba-qa-report-", "ba-spec-", "cleanliness-inspector-report-",
    "cleanliness-report-", "cleanup-execution-", "close-report", "combined-report-",
    "commit-qa-report-", "completion-", "context-", "dev-report-", "do-report-", "freshness-",
    "late-repair-run-", "overnight-log-", "overnight-summary-", "producer-answer-",
    "producer-question-", "prompt-inspector-report-", "prompt-report-", "qa-report-",
    "requirement-answers-", "requirement-round-", "rule-context-", "spec-",
    "style-inspector-report-", "style-partial-", "style-plan-", "style-report-",
    "test-writer-report-", "ticket-", "user-approvals-", "user-requirement-",
    "execution-context-", "execution-report-", "validation-report-", "validator-registry-",
)
_PROTECTED_COMPONENTS = (".claude", ".git")
# harness_temp_state scratch locations agents write their own output into.
AGENT_SCRATCH = ("claude-scratch", "codex-outputs", "graphify-cache")
# Git runs once per enclosing work tree (twice when one has no commit yet), each call capped
# by what remains of a 2.5 s budget, so the rule stays well inside its 5 s budget
# (lib/write_gate/__init__.py): an overrun of this fail-open rule would let the Write through,
# while a timeout here refuses. At most _MAX_TREES enclosing work trees are consulted.
_GIT_BUDGET = 2.5
_GIT_CALL_CAP = 1.2
_MAX_TREES = 4
_NO_REPO = "no-repo"


def _hts():
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)
    import harness_temp_state
    return harness_temp_state


def is_gate_read_artifact(path: str) -> bool:
    """True when `path` (one view, absolute) lies below a whole artifact root, or below an
    artifact root and is not a top-level markdown draft outside GATE_READ_PREFIXES. Case is
    folded, as harness_temp_state folds it (a case-insensitive filesystem maps
    docs/dev/Commit-QA-Report-T1.md onto the artifact)."""
    parts = [p.casefold() for p in path.split(os.sep) if p]
    for i in range(len(parts) - 2):
        pair = (parts[i], parts[i + 1])
        if pair in WHOLE_ARTIFACT_ROOTS:
            return True
        if pair in ARTIFACT_ROOTS:
            rel = parts[i + 2:]
            name = rel[-1]
            if len(rel) > 1 or not name.endswith(".md") or name.startswith(GATE_READ_PREFIXES):
                return True
    return False


def _has_protected_component(path: str) -> bool:
    return any(c.casefold() in _PROTECTED_COMPONENTS for c in path.split(os.sep))


def _views(file_path: str) -> tuple:
    """The path as written (normalised, links not followed), the parent's realpath plus the
    entry, and the full realpath."""
    written = os.path.normpath(os.path.abspath(file_path))
    head, tail = os.path.split(written)
    return tuple(dict.fromkeys((written, os.path.join(os.path.realpath(head), tail),
                                os.path.realpath(file_path))))


def _scratch_roots(hts) -> tuple:
    roots = [os.environ.get("TMPDIR") or "", "/var/tmp/claude-scratch"]
    roots += [os.path.join(r, "claude-scratch") for r in hts.name_roots()]
    out = []
    for r in roots:
        if r and os.path.isabs(r):
            real = os.path.realpath(r)
            if real != os.sep and real not in out:
                out.append(real)
    return tuple(out)


def _owner_sid(d: str):
    """The sid of `d`/.owner, None when there is no readable record."""
    try:
        with open(os.path.join(d, ".owner"), encoding="utf-8") as fh:
            rec = json.load(fh)
    except Exception:
        return None
    return rec.get("sid") if isinstance(rec, dict) else None


def _own_scratch(real: str, session_id: str, hts) -> bool:
    """`real` is below <root>/<session_id>/ for a session scratch root, with an .owner
    record naming this session (lib/scratch_owner.py)."""
    if not session_id or os.sep in session_id or session_id in (".", ".."):
        return False
    for root in _scratch_roots(hts):
        d = os.path.join(root, session_id)
        if real.startswith(d + os.sep) and _owner_sid(d) == session_id:
            return True
    return False


def _foreign_scratch(real: str, session_id: str, hts) -> bool:
    """An ancestor below a temp or name root holds an .owner record of another session."""
    roots = tuple(hts.temp_roots()) + tuple(hts.name_roots())
    d = os.path.dirname(real)
    while d and d != os.sep and any(d.startswith(r + os.sep) for r in roots):
        sid = _owner_sid(d)
        if sid is not None and sid != session_id:
            return True
        d = os.path.dirname(d)
    return False


def _in_harness_home(real: str) -> bool:
    try:
        if _LIB not in sys.path:
            sys.path.insert(0, _LIB)
        from claude_home import resolve
        home = resolve()
    except BaseException:
        return True
    if home is None:
        return False
    root = os.path.realpath(str(home))
    return root != os.sep and (real == root or real.startswith(root + os.sep))


def _in_project_scratch(real: str) -> bool:
    """Below a project's .claude/scratch/ (never the harness home's own)."""
    parts = [p.casefold() for p in real.split(os.sep)]
    return (any(parts[i] == ".claude" and parts[i + 1] == "scratch" for i in range(len(parts) - 2))
            and not _in_harness_home(real))


class _Doubt(Exception):
    """Git cannot answer for certain: the caller refuses."""


def _git(deadline: float, git_dir: str, work_tree: str, *args: str):
    """(returncode, stdout, stderr) of git on an explicit git dir and work tree, so no
    discovery, core.worktree, core.bare or GIT_* variable redirects it; system and global
    config are not read. Raises _Doubt when git cannot run or the budget runs out."""
    import time
    left = deadline - time.monotonic()
    if left <= 0.05:
        raise _Doubt("git budget spent")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_LITERAL_PATHSPECS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0")
    try:
        p = subprocess.run(["git", "--git-dir=" + git_dir, "--work-tree=" + work_tree,
                            "-c", "core.bare=false", "-C", work_tree, *args],
                           capture_output=True, text=True, timeout=min(_GIT_CALL_CAP, left),
                           env=env, stdin=subprocess.DEVNULL)
    except BaseException as exc:
        raise _Doubt(str(exc))
    return p.returncode, p.stdout, p.stderr


def _git_dir_of(top: str):
    """The git dir behind `top`/.git: the directory itself, or a linked worktree's git dir
    named by a `gitdir:` file whose back-link (<gitdir>/gitdir) names this .git. Raises
    _Doubt for anything else (a symlinked .git, a gitdir file without that back-link, such as
    a submodule's or one swapped to point at another repository)."""
    entry = os.path.join(top, ".git")
    if os.path.islink(entry):
        raise _Doubt("symlinked .git")
    if os.path.isdir(entry):
        return entry
    try:
        with open(entry, encoding="utf-8") as fh:
            line = fh.readline(4096).strip()
    except OSError as exc:
        raise _Doubt(str(exc))
    if not line.startswith("gitdir:"):
        raise _Doubt("unreadable .git file")
    git_dir = os.path.realpath(os.path.join(top, line[len("gitdir:"):].strip()))
    try:
        with open(os.path.join(git_dir, "gitdir"), encoding="utf-8") as fh:
            back = fh.readline(4096).strip()
    except OSError as exc:
        raise _Doubt("gitdir file without a back-link")
    if os.path.realpath(os.path.join(git_dir, back)) != os.path.realpath(entry):
        raise _Doubt("gitdir back-link names another work tree")
    return git_dir


def _enclosing_trees(real: str):
    """[(top, git dir)] for every directory above `real` holding a .git entry, innermost
    first. The work tree is where the .git entry sits, never what git reports for it."""
    out = []
    d = os.path.dirname(real)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            if len(out) >= _MAX_TREES:
                raise _Doubt("too many enclosing work trees")
            out.append((d, _git_dir_of(d)))
        parent = os.path.dirname(d)
        if parent == d:
            return out
        d = parent


def _tracks(deadline: float, top: str, git_dir: str, rel: str) -> bool:
    """Whether the work tree at `top` has `rel` in its index or in HEAD (a `git rm --cached`
    leaves it in HEAD)."""
    rc, out, err = _git(deadline, git_dir, top, "ls-files", "-z", "--with-tree=HEAD", "--", rel)
    if rc != 0 and "HEAD" in err:  # no commit yet: the index alone
        rc, out, err = _git(deadline, git_dir, top, "ls-files", "-z", "--", rel)
    if rc != 0:
        raise _Doubt(err.strip()[:200] or f"git exit {rc}")
    return bool(out.strip("\0"))


def _work_tree(real: str):
    """(innermost top, tracked): (_NO_REPO, False) outside every work tree; tracked is True
    when ANY enclosing work tree tracks the file (index or HEAD), None on doubt."""
    import time
    try:
        trees = _enclosing_trees(real)
        if not trees:
            return _NO_REPO, False
        deadline = time.monotonic() + _GIT_BUDGET
        for top, git_dir in trees:
            rel = os.path.relpath(real, top)
            if _tracks(deadline, top, git_dir, rel):
                return trees[0][0], True
        return trees[0][0], False
    except _Doubt:
        return None, None


def overwrite_exempt(file_path: str, session_id: str) -> bool:
    """True when the existing file `file_path` is scratch, temp or untracked generated output
    a Write may replace (see the module docstring). Any doubt answers False."""
    try:
        hts = _hts()
        views = _views(file_path)
        real = views[-1]
        if not os.path.isfile(real):
            return False
        locs = [hts.classify(v) for v in views]
        if any(loc is not None and loc.kind == hts.CONTROL for loc in locs):
            return False
        real_loc = locs[-1]
        own = _own_scratch(real, session_id, hts)
        agent_scratch = real_loc is not None and real_loc.name in AGENT_SCRATCH
        if real_loc is not None and not (agent_scratch or own):
            return False
        if _foreign_scratch(real, session_id, hts):
            return False
        if any(is_gate_read_artifact(v) for v in views):
            return False
        project_scratch = _in_project_scratch(real)
        if not project_scratch and (_has_protected_component(real) or _in_harness_home(real)):
            return False
        if os.stat(real).st_nlink > 1:
            return False
        top, tracked = _work_tree(real)
        if tracked is not False:
            return False
        if own or agent_scratch or project_scratch:
            return True
        if top != _NO_REPO:
            rel = os.path.relpath(real, top).split(os.sep)
            if rel[0] == os.pardir or any(c.startswith(".") for c in rel):
                return False  # .env, .vscode/...: configuration, in temp or not
        if hts.is_in_temp_root(real):
            return True
        return top != _NO_REPO
    except BaseException:
        return False
