#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM describing an EXTRACTED release archive.

The SBOM is built from the archive's real contents, not from the source
checkout, so its inventory necessarily corresponds to the bytes that ship:

  * one ``file`` component per archive member, each with its sha256, so a
    consumer can verify any individual file against the SBOM; plus
  * one ``library`` component per hash-pinned Python dependency, read from the
    lockfiles that are themselves inside the archive.

Usage:
  make_sbom.py --root <extracted-dir> --out <sbom.json>
               --name <component-name> --version <version> [--archive-sha256 <hex>]

Exit codes: 0 = written, 1 = nothing to describe (fail closed), 2 = usage error.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

LOCK_RE = re.compile(r"^([A-Za-z0-9._-]+)==([^\s\\]+)")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_components(root: str) -> list[dict]:
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            out.append({
                "type": "file",
                "name": rel,
                "hashes": [{"alg": "SHA-256", "content": sha256_of(full)}],
            })
    return sorted(out, key=lambda c: c["name"])


def library_components(root: str) -> list[dict]:
    """Hash-pinned Python deps, read from the lockfiles inside the archive."""
    seen: dict[tuple[str, str], set[str]] = {}
    lockdir = os.path.join(root, "requirements")
    if not os.path.isdir(lockdir):
        return []
    for name in sorted(os.listdir(lockdir)):
        if not name.endswith(".txt"):
            continue
        current = None
        for line in open(os.path.join(lockdir, name), encoding="utf8"):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            m = LOCK_RE.match(stripped)
            if m:
                current = (m.group(1).lower(), m.group(2))
                seen.setdefault(current, set())
            elif stripped.startswith("--hash=sha256:") and current:
                seen[current].add(stripped.split("--hash=sha256:", 1)[1].strip(" \\"))
    return [
        {
            "type": "library",
            "name": pkg,
            "version": ver,
            "purl": f"pkg:pypi/{pkg}@{ver}",
            "hashes": [{"alg": "SHA-256", "content": h} for h in sorted(hs)],
        }
        for (pkg, ver), hs in sorted(seen.items())
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--archive-sha256", default=None)
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        sys.stderr.write(f"make_sbom: not a directory: {args.root}\n")
        return 2
    files = file_components(args.root)
    libs = library_components(args.root)
    if not files:
        sys.stderr.write("make_sbom: archive contains no files — refusing to emit an empty SBOM\n")
        return 1

    metadata_component = {
        "type": "application",
        "name": args.name,
        "version": args.version,
        "bom-ref": f"pkg:generic/{args.name}@{args.version}",
    }
    if args.archive_sha256:
        metadata_component["hashes"] = [{"alg": "SHA-256", "content": args.archive_sha256}]

    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": metadata_component,
            "tools": [{"name": "make_sbom.py", "vendor": args.name}],
        },
        "components": libs + files,
    }
    with open(args.out, "w", encoding="utf8") as fh:
        json.dump(bom, fh, indent=2)
        fh.write("\n")
    sys.stderr.write(f"make_sbom: {len(files)} file component(s), {len(libs)} library component(s)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
