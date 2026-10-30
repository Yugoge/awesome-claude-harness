#!/usr/bin/env python3
"""aggregate-permissions.py — collect validated_permissions from qa-report-*.json.
Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
Outputs deduplicated permissions JSON list to stdout.
"""
import glob, json, os, sys


def extract(path):
    """The permissions QA validated in one report. A report this cannot read gives none: the
    report itself is decided on by its producer's stop and by the chain call at the cycle's end,
    which send it back to its QA dispatch; the next run of this step applies what it holds."""
    try:
        with open(path) as fh:
            perms = json.load(fh)["qa"]["permissions_verification"]["validated_permissions"]
    except KeyError:
        return []
    except (OSError, ValueError, TypeError) as exc:
        print(f"aggregate-permissions: {path}: no permissions read ({exc})", file=sys.stderr)
        return []
    return [p for p in perms if isinstance(p, dict)] if isinstance(perms, list) else []


if len(sys.argv) < 2:
    sys.exit("Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]")
src = sys.argv[1]
paths = sorted(glob.glob(os.path.join(src, "qa-report-*.json"))) if os.path.isdir(src) else sorted(glob.glob(src))
fixed = None
if len(sys.argv) > 2:
    fixed = {p["timestamp_suffix"] for p in json.load(open(sys.argv[2])) if p.get("status") == "fixed"}
paths = [p for p in paths if fixed is None or any(s in p for s in fixed)]
seen, out = set(), []
for perm in (perm for p in paths for perm in extract(p)):
    key = perm.get("pattern")
    if key and key not in seen:
        seen.add(key); out.append(perm)
json.dump(out, sys.stdout, indent=2)
