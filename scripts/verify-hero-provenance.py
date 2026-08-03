#!/usr/bin/env python3
"""Prove the committed hero capture is the product of a real, re-runnable run.

Description: Re-runs the demo, normalizes both outputs and byte-diffs them; verifies raw
  timing on RAW values; proves adversarially that the normalizer does not touch
  security-relevant text; and checks the manifest is an order-faithful bijection over the
  capture. Optionally exercises the status-block ratchet's full tamper table.

Usage: verify-hero-provenance.py [--skip-rerun] [--tamper]

Exit codes: 0 = every check held, 2 = one or more checks failed

BYTE-DIFF ON NORMALIZED TEXT, TIMING VERIFIED ON RAW VALUES. The normalizer scrubs
timestamps, so the diff can say nothing about duration. Checking only the diff would
leave a hand-edited timestamp column entirely unverified -- inside the one artifact whose
whole premise is that unverified content is the defect. Both are therefore checked, and
total duration alone is not enough: the per-event inter-arrival sequence is compared
element-wise, because checking only the endpoints permits every intermediate timestamp to
be edited so long as the ends still land in the window.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools/demo"))
from importlib import import_module  # noqa: E402

normalize = import_module("normalize-capture".replace("-", "_")) if False else None

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE = REPO_ROOT / ".github/assets/hero-capture.txt"
MANIFEST = REPO_ROOT / ".github/assets/guard-hero.json"
SVG = REPO_ROOT / ".github/assets/guard-hero.svg"
NORMALIZER = REPO_ROOT / "tools/demo/normalize-capture.py"
RESERVED_TASK_ID = "readme-hero-demo-reserved"

# Security-relevant classes. (a) fixed hook-emitted strings, anchored to committed source.
HOOK_ANCHORS = {
    "refusal": "BLOCKED:",
    "rule+reason": "agents are not authorized to push to remote from an agent context",
    "remedy-1": "For automated push, use the /push slash command",
    "remedy-2": "For human-driven push, exit the agent context",
    "consumption-marker": "[ALLOW-SENTINEL] grant CONSUMED for task_id=",
}

# One mutation per named category; each must make the normalized diff NON-empty.
NORMALIZER_MUTATIONS = {
    "rule name": ("BLOCKED: agent git push", "BLOCKED: agent git pull"),
    "reason": ("are not authorized to push", "are authorized to push"),
    "remedy": ("use the /push slash command", "use the /shove slash command"),
    "consumption marker": ("grant CONSUMED", "grant RETAINED"),
}

fails: list[str] = []


def fail(msg: str) -> None:
    fails.append(msg)


def norm_text(text: str) -> str:
    """Normalize via a real temp FILE. The normalizer takes a path and rejects a
    non-file; handing it /dev/stdin made it exit 1 with empty stdout, which silently
    turned all four mutation tests into vacuous comparisons of "" against ""."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text)
        tmp = fh.name
    try:
        r = subprocess.run([sys.executable, str(NORMALIZER), tmp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"normalizer exited {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout
    finally:
        Path(tmp).unlink(missing_ok=True)


def timestamps(text: str) -> list[float]:
    out = []
    for ln in text.splitlines():
        if ln.startswith("["):
            try:
                out.append(float(ln[1:ln.index("]")]))
            except ValueError:
                pass
    return out


def deltas(ts: list[float]) -> list[float]:
    return [round(b - a, 3) for a, b in zip(ts, ts[1:])]


def check_rerun() -> None:
    """AC13: regenerate and diff, plus raw timing on raw values."""
    with tempfile.TemporaryDirectory() as td:
        fresh = Path(td) / "fresh.txt"
        ev = Path(td) / "ev.json"
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/capture-hero-run.py"),
             "--capture", str(fresh), "--evidence", str(ev)],
            capture_output=True, text=True, cwd=str(REPO_ROOT))
        if r.returncode != 0:
            fail(f"fresh run failed (rc={r.returncode}): {r.stderr.strip()[:400]}")
            return
        fresh_text = fresh.read_text(encoding="utf-8")
        committed_text = CAPTURE.read_text(encoding="utf-8")

        if norm_text(fresh_text) != norm_text(committed_text):
            fail("normalized byte-diff between the fresh run and the committed "
                 "capture is NON-empty")

        ft, ct = timestamps(fresh_text), timestamps(committed_text)
        if len(ft) != len(ct):
            fail(f"event count differs: fresh={len(ft)} committed={len(ct)}")
            return
        fdur, cdur = ft[-1] - ft[0], ct[-1] - ct[0]
        if not (10.0 <= fdur <= 15.0):
            fail(f"fresh raw duration {fdur:.3f}s outside [10,15]")
        if abs(fdur - cdur) > 2.0:
            fail(f"fresh raw duration {fdur:.3f}s disagrees with committed "
                 f"{cdur:.3f}s by more than 2.0s")
        for i, (a, b) in enumerate(zip(deltas(ct), deltas(ft))):
            tol = max(0.5, abs(a) * 0.25)
            if abs(a - b) > tol:
                fail(f"inter-arrival delta {i} differs: committed={a}s fresh={b}s "
                     f"tolerance=±{tol:.3f}s")


def check_normalizer_is_not_lossy() -> None:
    """A lossy normalizer could make two fabrications equal. Prove it is not, per
    category, rather than sampling one category and generalizing."""
    base = CAPTURE.read_text(encoding="utf-8")
    base_norm = norm_text(base)
    for category, (old, new) in NORMALIZER_MUTATIONS.items():
        if old not in base:
            fail(f"normalizer mutation for {category!r} is vacuous: {old!r} absent "
                 f"from the capture")
            continue
        if norm_text(base.replace(old, new, 1)) == base_norm:
            fail(f"normalizer ERASES the {category!r} category — a mutation there left "
                 f"the normalized text unchanged")


def check_manifest_bijection() -> None:
    """AC17: order fidelity, security-class coverage, coverage arithmetic."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cap_lines = CAPTURE.read_text(encoding="utf-8").splitlines()
    lines = manifest["lines"]
    omitted = manifest.get("omitted", [])

    if len(lines) + len(omitted) != len(cap_lines):
        fail(f"coverage arithmetic fails: {len(lines)} + {len(omitted)} "
             f"!= {len(cap_lines)}")

    locs = [int(ln["source_locator"].rsplit(":", 1)[1]) for ln in lines]
    if any(b <= a for a, b in zip(locs, locs[1:])):
        fail("source_locator line numbers are not strictly increasing")

    for ln in lines:
        n = int(ln["source_locator"].rsplit(":", 1)[1])
        if not (1 <= n <= len(cap_lines)) or ln["text"] not in cap_lines[n - 1]:
            fail(f"{ln['id']}: text is not a verbatim slice of its declared locator")
        if ln["kind"] in ("condensation", "adaptation"):
            fail(f"{ln['id']}: forbidden kind {ln['kind']}")

    # (a) fixed hook-emitted strings must all be carried into the manifest.
    carried = "\n".join(ln["text"] for ln in lines)
    for name, anchor in HOOK_ANCHORS.items():
        if anchor in "\n".join(cap_lines) and anchor not in carried:
            fail(f"security-relevant class {name!r} is present in the capture but "
                 f"omitted from the manifest")
    # (b) channel/status-derived classes: any non-zero exit line must be carried.
    for i, raw in enumerate(cap_lines, start=1):
        if "exit 2" in raw or "exit 1" in raw:
            if i not in locs:
                fail(f"capture line {i} reports a non-zero exit but is not carried")
    # Discretionary omission of a visible line is forbidden.
    for o in omitted:
        if o.get("class") != "non-display":
            fail(f"omitted[] entry {o} is not a declared non-display class")

    # M4b non-disclosure across all three committed artifacts.
    for art in (CAPTURE, MANIFEST, SVG):
        text = art.read_text(encoding="utf-8", errors="replace")
        for ln in text.splitlines():
            if "/tmp/claude-grants/" in ln and RESERVED_TASK_ID not in ln:
                fail(f"{art.name} discloses a foreign grant path")
                break

    # The demo must never contain a deletion of the grant, nor the global-reaper path.
    demo = (REPO_ROOT / "examples/guard-demo/run-hero-demo.sh").read_text(encoding="utf-8")
    for forbidden in ("reap_expired_sentinel_grants", "stop-cleanup-allowlist.sh"):
        if forbidden in demo:
            fail(f"demo invokes the forbidden global-glob path {forbidden!r}")
    if "claude-grants" in demo and "unlink" in demo:
        fail("demo appears to delete a grant; only the real consumer may do that")


def check_tamper_table() -> None:
    """AC10: every mutation must produce a NEW failure naming the offending row."""
    gen = [sys.executable, str(REPO_ROOT / "scripts/generate-hero-status.py"), "--check"]
    readme = REPO_ROOT / "README.md"
    original = readme.read_text(encoding="utf-8")

    baseline = subprocess.run(gen, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if baseline.returncode != 0:
        fail(f"untampered ratchet already fails: {baseline.stderr.strip()[:300]}")
        return

    mutations = [
        ("1 flip capability-check to passed", "capability-check",
         lambda t: t.replace("id=capability-check state=not-yet",
                             "id=capability-check state=passed")),
        ("2 flip blackbox-tests to passed", "blackbox-tests",
         lambda t: t.replace("id=blackbox-tests state=not-yet",
                             "id=blackbox-tests state=passed")),
        ("3 delete the release row", "release",
         lambda t: "\n".join(l for l in t.splitlines()
                             if "id=release " not in l
                             and not l.startswith("- **Release**")) + "\n"),
        ("4 duplicate the os row", "os",
         lambda t: t.replace(
             "<!-- claim-row id=os state=partial evidence=.github/workflows tracked=none -->",
             "<!-- claim-row id=os state=partial evidence=.github/workflows tracked=none -->\n"
             "- **OS** — Ubuntu (CI) only; macOS unverified.\n"
             "<!-- claim-row id=os state=partial evidence=.github/workflows tracked=none -->",
             1)),
        ("5 reword a row, marker untouched", "release",
         lambda t: t.replace("- **Release** — unreleased (no tags).",
                             "- **Release** — shipping soon!")),
        ("6 state token outside the enum", "os",
         lambda t: t.replace("id=os state=partial", "id=os state=green")),
        ("7 flip supported-builds to passed", "supported-builds",
         lambda t: t.replace("id=supported-builds state=not-yet",
                             "id=supported-builds state=passed")),
        ("8a delete the known-limits row", "known-limits",
         lambda t: "\n".join(l for l in t.splitlines()
                             if "id=known-limits" not in l
                             and not l.startswith("**Known limits")) + "\n"),
        ("8b soften known-limits, marker untouched", "known-limits",
         lambda t: "\n".join(
             "**Known limits** — no tool is perfect; some gaps exist."
             if l.startswith("**Known limits") else l for l in t.splitlines()) + "\n"),
    ]
    try:
        for label, row_id, mutate in mutations:
            readme.write_text(mutate(original), encoding="utf-8")
            r = subprocess.run(gen, capture_output=True, text=True, cwd=str(REPO_ROOT))
            if r.returncode == 0:
                fail(f"tamper {label}: ratchet did NOT fail")
            elif row_id not in r.stderr:
                fail(f"tamper {label}: failure does not name row {row_id!r}: "
                     f"{r.stderr.strip()[:200]}")
    finally:
        readme.write_text(original, encoding="utf-8")

    restored = subprocess.run(gen, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if restored.returncode != 0:
        fail("after restoration the ratchet does not return to its untampered state")

    _positive_control()


def _positive_control() -> None:
    """Prove the ratchet is not merely fail-always, by REGENERATING in a scratch state
    where one guarded row's named predicate genuinely holds.

    Run in a throwaway git repo, never in this one: the predicate requires a COMMITTED
    artifact, and manufacturing one here would mutate the real index.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "scripts").mkdir(parents=True)
        (root / "docs/reference").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "scripts/generate-hero-status.py").write_text(
            (REPO_ROOT / "scripts/generate-hero-status.py").read_text(encoding="utf-8"),
            encoding="utf-8")
        (root / "docs/reference/install-compatibility-matrix.md").write_text(
            "# supported builds\n", encoding="utf-8")
        (root / ".github/workflows/ci.yml").write_text("runs-on: ubuntu-latest\n",
                                                       encoding="utf-8")
        (root / "README.md").write_text(
            "<!-- BEGIN canonical-region id=limits — generated by "
            "scripts/generate-hero-status.py; do not hand-edit -->\n"
            "<!-- END canonical-region id=limits -->\n\n"
            "<!-- BEGIN canonical-region id=status — generated by "
            "scripts/generate-hero-status.py; do not hand-edit -->\n"
            "<!-- END canonical-region id=status -->\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "scratch"]):
            subprocess.run(["git", *args], cwd=root, capture_output=True)

        gen = [sys.executable, str(root / "scripts/generate-hero-status.py")]
        subprocess.run([*gen, "--write"], cwd=root, capture_output=True, text=True)
        body = (root / "README.md").read_text(encoding="utf-8")
        if "id=supported-builds state=passed" not in body:
            fail("positive control: predicate did not flip supported-builds to passed "
                 "even though its artifact is committed in the scratch state")
            return
        r = subprocess.run([*gen, "--check"], cwd=root, capture_output=True, text=True)
        if r.returncode != 0 and "supported-builds" in r.stderr:
            fail(f"positive control: ratchet reports a failure for a row whose predicate "
                 f"genuinely holds: {r.stderr.strip()[:300]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-rerun", action="store_true")
    ap.add_argument("--tamper", action="store_true")
    a = ap.parse_args()

    check_normalizer_is_not_lossy()
    check_manifest_bijection()
    if not a.skip_rerun:
        check_rerun()
    if a.tamper:
        check_tamper_table()

    for f in fails:
        print(f"verify-hero-provenance: FAIL: {f}", file=sys.stderr)
    if fails:
        return 2
    print("verify-hero-provenance: OK — all provenance, timing and coverage checks held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
