#!/usr/bin/env python3
"""/spec's Design & Evidence Capture Routine: keep the user's design or evidence under the spec's per-id folder.

    spec-capture.py design   --spec PATH --turn N --slug TITLE [--from FILE]   (design text on stdin without --from)
    spec-capture.py evidence --spec PATH --from FILE

Both resolve the spec's de-prefixed id through scripts/resolve-spec-artifacts.py (its `candidates[0]`), create
`<project>/docs/dev/specs/<id>/design/` and `.../evidence/` (neither is one of the split's artifact names, so the
resolver still sees no split), and write one file there with an exclusive create, so an existing file is never
overwritten. The project is --project-dir, else $CLAUDE_PROJECT_DIR, else the git top level of the current directory.

design    writes `design/turn-<N>-<slug>.md`: stdin, or the bytes of --from, verbatim. The slug is the title
          lower-cased, every run of other characters a hyphen, 50 characters at most ("design" when nothing is left).
evidence  copies --from to `evidence/<name>`: the source's basename with every character that is not a letter, a
          digit or one of `._-` turned into `_` and `..` collapsed, so a name never leaves its folder.
A name that is taken gets `-<8 hex of the content's sha256>` before its extension (`photo.png` ->
`photo-1a2b3c4d.png`); a name taken by identical content is reused as it is.

Facts go to stdout as key=value lines; the exit status is 0 for both states below, 1 when the id cannot be
resolved, 2 for wrong arguments.
  spec_dir_id=<de-prefixed id>   bound_root=<absolute per-id folder>
  status=persisted  artifact=<project-relative path, the one a Section 9 reference line carries>
  status=failed     error=<why the source could not be read or written>   (nothing is archived)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RESOLVER = Path(__file__).resolve().parents[1] / "resolve-spec-artifacts.py"
MAX_STEM = 100


def emit(**facts: object) -> None:
    for key, value in facts.items():
        print(f"{key}={str(value).replace(chr(10), ' ')}")


def project_dir(given: str | None) -> Path:
    if given:
        return Path(given).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(top.stdout.strip() if top.returncode == 0 and top.stdout.strip() else os.getcwd()).resolve()


def spec_dir_id(spec: str, project: Path) -> str:
    """candidates[0] of the resolver's JSON: the de-prefixed stem. Its exit status is not read: the id is
    in the JSON whenever the spec file is readable, and a split that is not valid yet does not change it."""
    proc = subprocess.run([sys.executable, str(RESOLVER), "--spec-path", spec, "--project-dir", str(project)],
                          capture_output=True, text=True)
    try:
        return str(json.loads(proc.stdout)["candidates"][0])
    except (ValueError, KeyError, IndexError, TypeError):
        sys.stderr.write(proc.stderr or "spec-capture: the resolver gave no candidates\n")
        raise SystemExit(1)


def slugify(title: str) -> str:
    slug = re.sub(r"\W+", "-", title.lower()).strip("-_")[:50].strip("-")
    return slug or "design"


def safe_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    base = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in base)
    base = re.sub(r"\.{2,}", ".", base).lstrip(".")
    stem, ext = os.path.splitext(base)
    return f"{stem[:MAX_STEM]}{ext}" if stem else "evidence"


def place(folder: Path, name: str, data: bytes) -> Path:
    """Write `data` as folder/name, or folder/<stem>-<hash><ext> when that name is taken by other content."""
    digest = hashlib.sha256(data).hexdigest()
    stem, ext = os.path.splitext(name)
    for candidate in (name, f"{stem}-{digest[:8]}{ext}", f"{stem}-{digest[:16]}{ext}"):
        target = folder / candidate
        try:
            with open(target, "xb") as handle:
                handle.write(data)
            return target
        except FileExistsError:
            if target.is_file() and target.read_bytes() == data:
                return target
    raise OSError("every name for this content is taken by other content")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="spec-capture.py")
    parser.add_argument("kind", choices=("design", "evidence"))
    parser.add_argument("--spec", required=True)
    parser.add_argument("--turn", type=int)
    parser.add_argument("--slug")
    parser.add_argument("--from", dest="source")
    parser.add_argument("--project-dir")
    args = parser.parse_args(argv)
    if args.kind == "design" and (args.turn is None or args.turn < 1 or not args.slug):
        parser.error("design needs --turn N (1 or more) and --slug TITLE")
    if args.kind == "evidence" and not args.source:
        parser.error("evidence needs --from FILE")

    project = project_dir(args.project_dir)
    spec_id = spec_dir_id(args.spec, project)
    bound = project / "docs" / "dev" / "specs" / spec_id
    for sub in ("design", "evidence"):
        (bound / sub).mkdir(parents=True, exist_ok=True)
    emit(spec_dir_id=spec_id, bound_root=bound)

    try:
        if args.source:
            data = Path(args.source).read_bytes()
        else:
            data = sys.stdin.buffer.read()
        name = (f"turn-{args.turn}-{slugify(args.slug)}.md" if args.kind == "design"
                else safe_filename(args.source))
        target = place(bound / args.kind, name, data)
    except OSError as exc:
        emit(status="failed", error=exc.strerror or exc)
        return 0
    emit(status="persisted", artifact=target.relative_to(project).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
