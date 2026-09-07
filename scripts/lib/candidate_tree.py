#!/usr/bin/env python3
"""Build a *candidate tree*: the tree a dev cycle will actually ship.

An acceptance harness usually has to evaluate its criterion against neither the
committed tree (which predates the cycle's uncommitted work, so the criterion
passes or fails vacuously) nor the live checkout (which carries every unrelated
untracked file the developer happens to have on disk). It has to evaluate it
against COMMITTED CONTENT AT A REF, OVERLAID WITH THE FILES THE CYCLE DECLARED
IT WILL COMMIT. That third tree is what this module materialises.

Three properties are load-bearing, and each one exists because its absence has
already produced a wrong verdict:

CLOSED MEMBERSHIP. ``build_candidate_tree`` takes an EXPLICIT set of
repo-relative members and refuses to build when any of them is absent from the
working tree. There is deliberately no skip-if-missing branch: a harness that
silently drops a declared member reports a green criterion for a tree that can
never exist.

NO AMBIENT LEAK, BY CONSTRUCTION. The baseline is materialised with
``git clone --no-checkout`` + ``git read-tree --reset -u <ref>``, so the working
tree is *exactly* the ref's tree; the only other write is the explicit member
list. The source checkout's working tree is never enumerated, copied wholesale
or globbed, so an untracked file cannot reach the candidate tree even if the
caller wants it to. Widening the tree requires naming a member.

SELF-DESCRIBING. Each overlaid member is recorded in the CANDIDATE TREE'S OWN
index, at an explicit mode, via ``git update-index --cacheinfo``. A caller can
therefore ask the candidate tree "is this path tracked, and at what mode"
instead of asking a different tree and hoping the answer transfers. Plumbing is
used rather than ``git add`` so that a ``.gitignore`` in the baseline cannot
silently drop a declared member -- membership is closed, and ignore rules do not
get a vote.

``derive_declaration`` closes the last hole: the member set is DERIVED from the
dev-report JSON documents a task already recorded (the aggregate report plus its
per-lane shards), restricted to the reports that agree on one baseline commit, so
it cannot drift from the cycle's own declaration the way a re-typed list does.
It reads THREE declaration categories, because two are not enough to say what a
cycle ships: see ``DEFAULT_DECLARATION_FIELDS``.

Nothing here is specific to a task, lane or filename: task id, ref, destination
and member set are all parameters.

Usage (CLI):
  candidate_tree.py derive --reports-dir DIR --task-id ID [--json]
  candidate_tree.py build  --repo DIR --dest DIR --task-id ID
                           [--reports-dir DIR] [--ref REF]

Exit codes: 0 = success, 1 = build/derivation failure, 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Repository conventions, not cycle constants: every one is a parameter default.
DEFAULT_REPORT_PREFIX = "dev-report-"
DEFAULT_BASELINE_FIELD = "baseline_head_sha"
DEFAULT_DECLARATION_CONTAINER = "dev"
# THREE categories, not two, and the third is not a synonym for the first.
# `files_created` and `files_modified` are GIT-DERIVED: a report fills them from
# `git ls-files --others` and `git diff --name-only` against its own baseline.
# That derivation is authorship-shaped, so by construction it cannot express a
# path the cycle did NOT author but now hard-requires in the tree it ships -- a
# file that already existed untracked, which a change made load-bearing. Such a
# path lands in a purely observational field instead, the candidate tree is built
# without it, and the criterion then fails for a requirement the records never
# stated. `files_required_to_ship` is that missing category: DECLARED rather than
# derived, and carrying no claim of authorship. Membership still comes only from
# a report -- nothing enters a tree by existing on the machine.
DEFAULT_DECLARATION_FIELDS = (
    "files_created",
    "files_modified",
    "files_required_to_ship",
)

MODE_REGULAR = "100644"
MODE_EXECUTABLE = "100755"
MODE_SYMLINK = "120000"


class CandidateTreeError(RuntimeError):
    """Any failure to produce or describe a candidate tree."""


class DeclaredPathError(CandidateTreeError):
    """A declared member is not a usable repo-relative path."""


class MissingDeclaredMembers(CandidateTreeError):
    """One or more declared members are absent from the working tree.

    Raised BEFORE anything is materialised, so a failed build leaves no
    half-populated destination to be mistaken for a usable tree.
    """

    def __init__(self, missing, source_repo):
        self.missing = tuple(missing)
        self.source_repo = str(source_repo)
        super().__init__(
            "candidate tree: %d declared member(s) absent from the working tree "
            "at %s: %s" % (len(self.missing), self.source_repo, ", ".join(self.missing))
        )


class DeclarationError(CandidateTreeError):
    """A task's recorded declaration could not be derived."""


def _git(repo, *args, check=True, stdin_text=None):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, input=stdin_text,
    )
    if check and proc.returncode != 0:
        raise CandidateTreeError(
            "git %s failed in %s: %s" % (" ".join(args), repo, proc.stderr.strip())
        )
    return proc.stdout


def normalise_member(member) -> str:
    """Repo-relative, non-escaping, POSIX-normalised member path."""
    if not isinstance(member, str) or not member.strip():
        raise DeclaredPathError("declared member must be a non-empty string, got %r" % (member,))
    pure = PurePosixPath(member.strip())
    if pure.is_absolute():
        raise DeclaredPathError("declared member must be repo-relative, got %r" % (member,))
    parts = [p for p in pure.parts if p != "."]
    if not parts:
        raise DeclaredPathError("declared member must name a file, got %r" % (member,))
    if ".." in parts:
        raise DeclaredPathError("declared member must not escape the repository: %r" % (member,))
    if ".git" in parts:
        raise DeclaredPathError("declared member must not address the git directory: %r" % (member,))
    return str(PurePosixPath(*parts))


@dataclass(frozen=True)
class OverlayEntry:
    """One member as it was recorded in the candidate tree's index."""

    path: str
    mode: str
    blob: str


@dataclass(frozen=True)
class CandidateTree:
    root: Path
    ref: str
    baseline_commit: str
    overlay: tuple

    def tracked_mode(self, path) -> str | None:
        """Mode this path carries in THIS tree's index, or None if untracked."""
        out = _git(self.root, "ls-files", "--stage", "--", normalise_member(path))
        line = out.strip().splitlines()
        return line[0].split()[0] if line else None

    def manifest(self) -> dict:
        return {
            "root": str(self.root),
            "ref": self.ref,
            "baseline_commit": self.baseline_commit,
            "overlay": [
                {"path": e.path, "mode": e.mode, "blob": e.blob} for e in self.overlay
            ],
        }


def build_candidate_tree(source_repo, dest, ref, declared, *, hardlinks=False) -> CandidateTree:
    """Materialise `ref`'s committed content overlaid with `declared` members.

    `declared` is the closed member set: every entry must exist in
    `source_repo`'s working tree or the build raises MissingDeclaredMembers.
    """
    source_repo = Path(source_repo).resolve()
    dest = Path(dest)
    members = sorted({normalise_member(m) for m in declared})

    # Closed membership is enforced before any materialisation: a build either
    # produces the whole declared tree or produces nothing at all.
    missing = [m for m in members if not os.path.lexists(source_repo / m)]
    if missing:
        raise MissingDeclaredMembers(missing, source_repo)
    for m in members:
        src = source_repo / m
        if not src.is_symlink() and not src.is_file():
            raise DeclaredPathError("declared member is not a regular file or symlink: %s" % m)

    if dest.exists() and any(dest.iterdir()):
        raise CandidateTreeError("candidate tree destination is not empty: %s" % dest)

    commit = _git(source_repo, "rev-parse", "--verify", "%s^{commit}" % ref).strip()

    clone = ["clone", "--quiet", "--no-checkout"]
    if not hardlinks:
        clone.append("--no-hardlinks")
    proc = subprocess.run(
        ["git", *clone, str(source_repo), str(dest)], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise CandidateTreeError("cloning %s into %s failed: %s" % (source_repo, dest, proc.stderr.strip()))

    if subprocess.run(
        ["git", "-C", str(dest), "cat-file", "-e", "%s^{commit}" % commit],
        capture_output=True,
    ).returncode != 0:
        raise CandidateTreeError(
            "ref %r resolves to %s in %s but that commit is not reachable from any "
            "cloned ref, so the baseline cannot be materialised" % (ref, commit, source_repo)
        )

    # HEAD is left on the clone's default branch and only the index and working
    # tree are reset to the ref. No branch is created and no history is
    # rewritten, so a consumer that requires a checked-out branch still finds
    # one while the CONTENT is exactly the ref's tree.
    _git(dest, "read-tree", "--reset", "-u", commit)

    overlay = []
    for m in members:
        src = source_repo / m
        dst = dest / m
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        if src.is_symlink():
            target = os.readlink(src)
            os.symlink(target, dst)
            mode = MODE_SYMLINK
            blob = _git(dest, "hash-object", "-w", "--stdin", stdin_text=target).strip()
        else:
            shutil.copyfile(src, dst)
            src_mode = src.stat().st_mode
            os.chmod(dst, src_mode & 0o777)
            mode = MODE_EXECUTABLE if src_mode & 0o111 else MODE_REGULAR
            blob = _git(dest, "hash-object", "-w", "--", str(dst)).strip()
        # Plumbing, not `git add`: an ignore rule inherited from the baseline
        # must not get a vote on a member the caller declared.
        _git(dest, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, blob, m))
        overlay.append(OverlayEntry(path=m, mode=mode, blob=blob))

    return CandidateTree(root=dest, ref=str(ref), baseline_commit=commit, overlay=tuple(overlay))


@dataclass(frozen=True)
class Declaration:
    """What a task recorded it will commit, and which reports said so."""

    task_id: str
    baseline: str
    paths: tuple
    reports: tuple
    excluded: tuple


def discover_reports(reports_dir, task_id, *, report_prefix=DEFAULT_REPORT_PREFIX):
    """The task's aggregate report plus its per-lane shard reports, sorted.

    Matching is literal rather than glob-based so a task id containing glob
    metacharacters cannot silently select the wrong documents.
    """
    directory = Path(reports_dir)
    if not directory.is_dir():
        raise DeclarationError("reports directory does not exist: %s" % directory)
    aggregate = "%s%s.json" % (report_prefix, task_id)
    shard_prefix = "%s%s-" % (report_prefix, task_id)
    names = [
        n for n in sorted(os.listdir(directory))
        if n == aggregate or (n.startswith(shard_prefix) and n.endswith(".json"))
    ]
    return [directory / n for n in names]


def _read_report(path, baseline_field, container, fields):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeclarationError("unreadable dev-report %s: %s" % (path, exc)) from exc
    baseline = doc.get(baseline_field)
    baseline = baseline.strip() if isinstance(baseline, str) and baseline.strip() else None
    node = doc.get(container) or {}
    declared = []
    for field in fields:
        value = node.get(field)
        if value is None:
            continue
        if not isinstance(value, list):
            raise DeclarationError("%s: %s.%s must be a list, got %r" % (path, container, field, type(value).__name__))
        declared.extend(str(v) for v in value)
    return baseline, declared


def derive_declaration(reports_dir, task_id, *, baseline=None,
                       report_prefix=DEFAULT_REPORT_PREFIX,
                       baseline_field=DEFAULT_BASELINE_FIELD,
                       container=DEFAULT_DECLARATION_CONTAINER,
                       fields=DEFAULT_DECLARATION_FIELDS) -> Declaration:
    """Union of every declared path across the reports agreeing on one baseline.

    "Declared" is `fields`: the git-derived created/modified sets plus the paths
    a report states it requires in the shipped tree without claiming to have
    authored them.

    Reports recording a different baseline (or none) describe a different tree,
    so they are EXCLUDED rather than merged: merging them would declare files
    whose content belongs to another cycle's starting point.
    """
    reports = discover_reports(reports_dir, task_id, report_prefix=report_prefix)
    if not reports:
        raise DeclarationError(
            "no %s%s*.json dev-reports under %s" % (report_prefix, task_id, reports_dir))
    parsed = [(p, *_read_report(p, baseline_field, container, fields)) for p in reports]

    if baseline is None:
        aggregate = "%s%s.json" % (report_prefix, task_id)
        recorded = [b for p, b, _ in parsed if p.name == aggregate and b]
        if recorded:
            baseline = recorded[0]
        else:
            counts = Counter(b for _, b, _ in parsed if b)
            if not counts:
                raise DeclarationError(
                    "no dev-report for %s records a %s" % (task_id, baseline_field))
            baseline = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    paths, included, excluded = set(), [], []
    for path, recorded, declared in parsed:
        if recorded == baseline:
            included.append(path.name)
            paths.update(declared)
        else:
            excluded.append((path.name, recorded))
    if not included:
        raise DeclarationError(
            "no dev-report for %s records baseline %s" % (task_id, baseline))
    return Declaration(
        task_id=str(task_id), baseline=baseline, paths=tuple(sorted(paths)),
        reports=tuple(included), excluded=tuple(excluded),
    )


def build_from_declaration(source_repo, dest, reports_dir, task_id, *, ref=None,
                           hardlinks=False, **derive_kwargs):
    """Candidate tree for a task, from its own recorded declaration.

    `ref` defaults to the baseline the declaration itself agrees on, so the
    committed content and the overlaid members describe the same cycle.
    """
    declaration = derive_declaration(reports_dir, task_id, **derive_kwargs)
    tree = build_candidate_tree(
        source_repo, dest, ref or declaration.baseline, declaration.paths, hardlinks=hardlinks)
    return tree, declaration


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("derive", help="print a task's derived declared set")
    d.add_argument("--reports-dir", required=True)
    d.add_argument("--task-id", required=True)
    d.add_argument("--json", action="store_true")

    b = sub.add_parser("build", help="materialise a candidate tree for a task")
    b.add_argument("--repo", required=True)
    b.add_argument("--dest", required=True)
    b.add_argument("--task-id", required=True)
    b.add_argument("--reports-dir", default="docs/dev")
    b.add_argument("--ref", default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "derive":
            decl = derive_declaration(args.reports_dir, args.task_id)
            if args.json:
                print(json.dumps({
                    "task_id": decl.task_id, "baseline": decl.baseline,
                    "paths": list(decl.paths), "reports": list(decl.reports),
                    "excluded": [{"report": r, "baseline": b} for r, b in decl.excluded],
                }, indent=2))
            else:
                for path in decl.paths:
                    print(path)
        else:
            tree, _ = build_from_declaration(
                args.repo, args.dest, args.reports_dir, args.task_id, ref=args.ref)
            print(json.dumps(tree.manifest(), indent=2))
    except CandidateTreeError as exc:
        print("candidate-tree: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
