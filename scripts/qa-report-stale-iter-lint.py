#!/usr/bin/env python3
"""Lint qa-report-<task>.json for stale prior-iteration failure text that
lacks an explicit resolution marker.

Defends against the F2 pattern from close-debate of task 20260529-210616:
the qa-report had qa.status="pass" alongside untouched iter-1 failure text
in spec_section_updates.section_4 AND success_criteria_results[0].details
— a self-contradiction that violated the user theme "harness 别再骗你".

Invariant: when qa.status == "pass" AND resolved_findings[] is non-empty
(an iter-N -> N+1 transition occurred), every failure-keyword sentence in
spec_section_updates.* AND success_criteria_results[*].details MUST also
contain a resolution marker in the SAME sentence.

Exit codes:
  0  verdict=ok OR verdict=skipped (no lint applicable)
  5  verdict=stale_text_detected (precondition unmet for close-pass)
  1  malformed JSON, file not found, usage error
"""
import argparse
import json
import re
import sys

FAILURE_KEYWORDS = [
    r"CAVEAT:",
    r"\bnot exercised\b",
    r"\bdrift detected\b",
    r"\brejected with exit\s+\d",
    r"\brejects[^\.;]*?with exit\s+\d",
    r"\bfailed with exit\s+\d",
    r"\bfails with exit\s+\d",
    r"spec_text_vs_execution_drift detected",
]
RESOLUTION_MARKERS = [
    r"\bwas resolved\b",
    r"\bresolved iter-?\d",
    r"\bhistorical\b",
    r"\bsee resolved_findings\b",
    r"\bverified iter-?\d",
    r"\bcleared iter-?\d",
]

KW_RE = re.compile("|".join(FAILURE_KEYWORDS), re.IGNORECASE)
RES_RE = re.compile("|".join(RESOLUTION_MARKERS), re.IGNORECASE)


def split_sentences(text):
    parts = re.split(r"(?<=[.;])\s+", text)
    return [p for p in parts if p.strip()]


def scan_text(text, location):
    findings = []
    for sentence in split_sentences(text):
        if KW_RE.search(sentence) and not RES_RE.search(sentence):
            findings.append({"location": location, "sentence": sentence.strip()[:300]})
    return findings


def lint(report):
    qa = report.get("qa", {})
    if qa.get("status") != "pass":
        return {"verdict": "skipped", "reason": "qa.status != pass; lint only applies to pass reports"}
    if not qa.get("resolved_findings"):
        return {"verdict": "skipped", "reason": "no resolved_findings[] — no prior iteration to lint against"}
    findings = []
    ssu = qa.get("spec_section_updates", {}) or {}
    for key, val in ssu.items():
        if isinstance(val, str):
            findings.extend(scan_text(val, f"qa.spec_section_updates.{key}"))
    for i, sc in enumerate(qa.get("success_criteria_results", []) or []):
        det = sc.get("details") or ""
        if isinstance(det, str):
            findings.extend(scan_text(det, f"qa.success_criteria_results[{i}].details"))
    if findings:
        return {
            "verdict": "stale_text_detected",
            "findings": findings,
            "remedy": "edit each location to either (a) delete the prior-iteration failure text, or (b) add a resolution marker like 'was resolved iter-2 (see resolved_findings[])' in the SAME sentence",
        }
    return {"verdict": "ok"}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--report-file", required=True, help="path to qa-report-<task>.json")
    args = p.parse_args()
    try:
        with open(args.report_file) as f:
            report = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: not found: {args.report_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {args.report_file}: {e}", file=sys.stderr)
        sys.exit(1)
    result = lint(report)
    print(json.dumps(result, indent=2))
    if result["verdict"] == "stale_text_detected":
        sys.exit(5)
    sys.exit(0)


if __name__ == "__main__":
    main()
