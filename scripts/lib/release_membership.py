#!/usr/bin/env python3
"""Resolve the release-membership manifest into a concrete path set.

Single source of truth shared by every consumer, so the archive builder, the
residue gate and the published-artifact verifier can never disagree about what
ships:

  * ``.github/workflows/release.yml``     — builds the archive from this set
  * ``scripts/check-public-core.sh``      — asserts the EXTRACTED archive's path
                                            set equals this set
  * ``scripts/verify-release-manifest.sh`` — re-asserts it against the DOWNLOADED
                                            published asset

Two modes:

  --from-git   resolve against tracked paths (build time, in a checkout)
  --from-tree  resolve against files actually present under a directory
               (verification time, against an extracted archive)

Usage:
  release_membership.py --from-git  [--root DIR] [--manifest FILE]
  release_membership.py --from-tree --root DIR [--manifest FILE]

Exit codes: 0 = resolved (path set on stdout, one per line, sorted),
            1 = manifest unreadable / no paths resolved (fail closed),
            2 = usage error.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys

DEFAULT_MANIFEST = "release-membership.v1.json"


def _matches(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if pat.endswith("/**"):
            if path == pat[:-3] or path.startswith(pat[:-2]):
                return True
        elif fnmatch.fnmatchcase(path, pat) or path == pat:
            return True
    return False


def resolve(root: str, manifest_path: str, from_git: bool) -> list[str]:
    with open(manifest_path, encoding="utf8") as fh:
        manifest = json.load(fh)
    include = manifest.get("include") or []
    exclude = manifest.get("exclude") or []
    if not include:
        raise SystemExit("release-membership: manifest has an empty include set")

    if from_git:
        out = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True)
        if out.returncode != 0:
            raise SystemExit(f"release-membership: git ls-files failed in {root}")
        candidates = out.stdout.split("\n")
    else:
        candidates = []
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in files:
                candidates.append(os.path.relpath(os.path.join(dirpath, name), root))

    selected = sorted(
        p for p in candidates
        if p and _matches(p, include) and not _matches(p, exclude)
    )
    return selected


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-git", action="store_true")
    src.add_argument("--from-tree", action="store_true")
    ap.add_argument("--root", default=".")
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args(argv)

    manifest_path = args.manifest or os.path.join(args.root, DEFAULT_MANIFEST)
    if not os.path.isfile(manifest_path):
        sys.stderr.write(f"release-membership: manifest not found: {manifest_path}\n")
        return 1
    paths = resolve(args.root, manifest_path, args.from_git)
    if not paths:
        sys.stderr.write("release-membership: resolved an EMPTY path set — refusing (fail closed)\n")
        return 1
    sys.stdout.write("\n".join(paths) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
