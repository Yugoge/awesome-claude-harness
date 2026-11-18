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
    every directory holding a .git entry (never by asking git). Git never sees a
    repository's own git dir or config: each question goes to a fresh shadow git dir the
    rule writes (HEAD = the commit id the rule resolved itself from HEAD and refs, an empty
    refs/, a config holding only repositoryformatversion), with the real index and object
    store passed as data (GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY); see _GIT_HARDENING. A .git
    file counts only as a linked worktree with the shape git gives one; a symlinked .git,
    a submodule's .git file, an unborn HEAD in a repository that has refs, or an unknown
    repository extension is doubt.

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
command or step script reads (a role's own scratch directory or docs/codex/ notes,
build/out.txt, or docs/dev/arch-probe.md for an actor tool-policy lets write docs/dev/) may be
replaced; a report, context, ticket, manifest, grant or spec that a later gate trusts keeps the
Edit-only rule even when untracked, so a Write-only role writes it once, complete.

Known limits (each needs shell git surgery, not file Writes alone): an artifact a dispatch's
obligation declares at a path no command template uses is protected only under an artifact
root or when tracked; a file below a submodule's .git file is never exempt; a project whose
.git dir was moved away (or replaced by a fully forged linked-worktree layout) has no index
to ask; a work tree joined to its git dir only by core.worktree, with no .git entry, reads
as no repository (so as plain temp when in temp); untracked output in a harness worktree
under <project>/.claude/worktrees/ stays refused by the .claude rule.
"""
from __future__ import annotations

import json
import os
import re
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
# Git runs once per enclosing work tree, each call capped by what remains of a 2.5 s budget,
# so the rule stays well inside its 5 s budget (lib/write_gate/__init__.py): an overrun of
# this fail-open rule would let the Write through, while a timeout here refuses. At most
# _MAX_TREES enclosing work trees are consulted.
_GIT_BUDGET = 2.5
_GIT_CALL_CAP = 1.2
_MAX_TREES = 4
# Repository extensions the shadow git dir can stand in for; any other (objectformat,
# refstorage, ...) is doubt.
_SAFE_EXTENSIONS = frozenset({"worktreeconfig", "preciousobjects", "partialclone", "noop"})
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


# How git is run, robust by construction: git never sees the repository's own git dir.
# Every call goes to a fresh shadow git dir the rule writes itself (HEAD = the commit id the
# rule resolved, an empty refs/, and a config holding only repositoryformatversion), with
# the real index (GIT_INDEX_FILE) and the real object store (GIT_OBJECT_DIRECTORY), both
# data git parses, never configuration. Nothing an agent can write is read as git config:
# the repository's config, config.worktree, includes, hooks, info/ and refs/ (replace refs
# included) are not in the shadow dir; system and global config are off
# (GIT_CONFIG_NOSYSTEM, GIT_CONFIG_GLOBAL=/dev/null); every GIT_* variable from the caller is
# dropped. The -c and environment switches below are a second layer: they turn off each
# execution-capable feature a config could have named anyway (fsmonitor, hooks, any
# transport and lazy fetch, replace objects, pagers, askpass, ssh).
_GIT_HARDENING = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
                  "-c", "protocol.allow=never", "-c", "core.useReplaceRefs=false",
                  "-c", "core.bare=false", "-c", "core.sshCommand=false",
                  "-c", "core.askPass=false", "-c", "credential.helper=",
                  "-c", "core.pager=cat", "-c", "core.untrackedCache=false",
                  "-c", "index.skipHash=false")


def _git(deadline: float, shadow: str, index: str, objects: str, work_tree: str, *args: str):
    import time
    left = deadline - time.monotonic()
    if left <= 0.05:
        raise _Doubt("git budget spent")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_LITERAL_PATHSPECS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
               GIT_TERMINAL_PROMPT="0", GIT_INDEX_FILE=index, GIT_OBJECT_DIRECTORY=objects,
               GIT_CONFIG_PARAMETERS="", GIT_PROTOCOL_FROM_USER="0", GIT_ALLOW_PROTOCOL="")
    try:
        p = subprocess.run(["git", "--git-dir=" + shadow, "--work-tree=" + work_tree,
                            *_GIT_HARDENING, "-C", work_tree, *args],
                           capture_output=True, text=True, timeout=min(_GIT_CALL_CAP, left),
                           env=env, stdin=subprocess.DEVNULL)
    except BaseException as exc:
        raise _Doubt(str(exc))
    return p.returncode, p.stdout, p.stderr


def _read_line(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readline(4096).strip()
    except (OSError, UnicodeError) as exc:
        raise _Doubt(f"unreadable {path}: {exc}")


def _git_dir_of(top: str, project: str = ""):
    """The git dir behind `top`/.git: the directory itself, or the git dir of a linked
    worktree (`git worktree add`) named by a `gitdir:` file. A linked worktree's git dir must
    have the shape git gives it: <common>/worktrees/<name>/ with a commondir file naming
    <common>, a real git dir holding HEAD and objects/, and a gitdir back-link naming this
    .git. Anything else raises _Doubt: a symlinked .git, a submodule's .git file, one
    pointing at another repository, a back-link alone."""
    entry = os.path.join(top, ".git")
    if os.path.islink(entry):
        raise _Doubt("symlinked .git")
    if os.path.isdir(entry):
        return entry
    line = _read_line(entry)
    if not line.startswith("gitdir:"):
        raise _Doubt("unreadable .git file")
    git_dir = os.path.realpath(os.path.join(top, line[len("gitdir:"):].strip()))
    back = _read_line(os.path.join(git_dir, "gitdir"))
    if os.path.realpath(os.path.join(git_dir, back)) != os.path.realpath(entry):
        raise _Doubt("gitdir back-link names another work tree")
    worktrees = os.path.dirname(git_dir)
    common = os.path.dirname(worktrees)
    if os.path.basename(worktrees) != "worktrees" or _common_dir(git_dir) != common:
        raise _Doubt("not a linked worktree's git dir")
    if not (os.path.isfile(os.path.join(common, "HEAD"))
            and os.path.isdir(os.path.join(common, "objects"))):
        raise _Doubt("linked worktree without a common git dir")
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


_SHA = re.compile(r"^[0-9a-f]{40}$")


def _common_dir(git_dir: str) -> str:
    cd = os.path.join(git_dir, "commondir")
    if os.path.lexists(cd):
        return os.path.realpath(os.path.join(git_dir, _read_line(cd)))
    return git_dir


def _check_extensions(common: str) -> None:
    """Read (never execute) the repository's config for extensions the shadow cannot
    stand in for."""
    try:
        with open(os.path.join(common, "config"), encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _Doubt(str(exc))
    section = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if line.startswith("["):
            section = line.strip("[]").split()[0].strip('"').casefold() if line.strip("[]").split() else ""
            continue
        if section == "extensions" and line:
            key = line.split("=", 1)[0].strip().casefold()
            if key not in _SAFE_EXTENSIONS:
                raise _Doubt(f"repository extension {key}")


def _ref(common: str, git_dir: str, name: str):
    """The commit id `name` (refs/...) points at, None when the ref does not exist."""
    for base in (git_dir, common):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            value = _read_line(path)
            if value.startswith("ref:"):
                raise _Doubt("nested symbolic ref")
            if not _SHA.match(value):
                raise _Doubt(f"unreadable ref {name}")
            return value
    packed = os.path.join(common, "packed-refs")
    try:
        with open(packed, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 2 and parts[1] == name and _SHA.match(parts[0]):
                    return parts[0]
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise _Doubt(str(exc))
    return None


def _has_any_ref(common: str) -> bool:
    heads = os.path.join(common, "refs")
    for _root, _dirs, files in os.walk(heads):
        if files:
            return True
    try:
        with open(os.path.join(common, "packed-refs"), encoding="utf-8", errors="replace") as fh:
            return any(line.strip() and not line.startswith(("#", "^")) for line in fh)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _Doubt(str(exc))


def _head_commit(git_dir: str, common: str):
    """HEAD's commit id; None only for a repository with no ref at all (a fresh `git init`).
    An unborn HEAD in a repository that has refs is doubt."""
    head = _read_line(os.path.join(git_dir, "HEAD"))
    if _SHA.match(head):
        return head
    if not head.startswith("ref:"):
        raise _Doubt("unreadable HEAD")
    name = head[len("ref:"):].strip()
    if not name.startswith("refs/") or ".." in name.split("/"):
        raise _Doubt("odd HEAD ref")
    commit = _ref(common, git_dir, name)
    if commit is None and _has_any_ref(common):
        raise _Doubt("unborn HEAD in a repository with refs")
    return commit


def _tracks(deadline: float, top: str, git_dir: str, rel: str) -> bool:
    """Whether the work tree at `top` has `rel` in its index or in HEAD (a `git rm --cached`
    leaves it in HEAD), asked through a shadow git dir (see _GIT_HARDENING)."""
    import shutil
    import tempfile
    common = _common_dir(git_dir)
    _check_extensions(common)
    commit = _head_commit(git_dir, common)
    objects = os.path.join(common, "objects")
    if not os.path.isdir(objects):
        raise _Doubt("no object store")
    shadow = tempfile.mkdtemp(prefix="overwrite-shadow-")
    try:
        os.mkdir(os.path.join(shadow, "refs"))
        os.mkdir(os.path.join(shadow, "objects"))
        with open(os.path.join(shadow, "HEAD"), "w") as fh:
            fh.write((commit or "ref: refs/heads/unborn") + "\n")
        with open(os.path.join(shadow, "config"), "w") as fh:
            fh.write("[core]\n\trepositoryformatversion = 0\n")
        index = os.path.join(git_dir, "index")
        args = ["ls-files", "-z"] + (["--with-tree=" + commit] if commit else []) + ["--", rel]
        rc, out, err = _git(deadline, shadow, index, objects, top, *args)
    finally:
        shutil.rmtree(shadow, ignore_errors=True)
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
