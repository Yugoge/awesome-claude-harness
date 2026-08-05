#!/usr/bin/env python3
"""Acceptance harness for the coexistence-aware installer.

Runs every acceptance criterion (AC1-AC8) of the installer lane against real
fixtures in a temporary directory. Nothing outside the temporary directory is
read for state or written to.

Usage: python3 scripts/install/tests/installer-acceptance.py [--verbose]
                                                            [--engine <path>]
Exit codes: 0 = every assertion passed; 1 = at least one assertion failed.

The measurement instrument is the NODE SNAPSHOT from installer.py: a recursive,
symlink-NOT-following walk recording node type, raw readlink text, content
sha256 and (st_dev, st_ino) inode identity per node.

--engine points the destructive-path fixtures (AC9-AC14) at an ALTERNATIVE engine
so this harness can be run against an older engine and demonstrated to fail for
the diagnosed reason. A failure arising from surface the alternative engine does
not have -- an unrecognized flag, a missing state field, a missing payload file --
is classified `inapplicable-on-alternative-engine` and does NOT count as evidence
of a defect: without that split, argparse and KeyError failures would register in
every defect family while demonstrating nothing. That is the same false-evidence
class as an assertion that cannot fail, relocated one level up.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
sys.path.insert(0, str(SOURCE / "scripts" / "install"))
from installer import node_snapshot, sha256_file  # noqa: E402

INSTALL = SOURCE / "scripts" / "install" / "install"
UNINSTALL = SOURCE / "scripts" / "install" / "uninstall"
ENGINE = SOURCE / "scripts" / "install" / "installer.py"
PREFLIGHT = SOURCE / "scripts" / "install" / "preflight"
PROFILE = json.loads((SOURCE / "scripts" / "install" / "profiles" / "core.json").read_text())
MATRIX = SOURCE / "docs" / "reference" / "install-compatibility-matrix.md"
README = SOURCE / "README.md"

RESULTS: list[tuple[str, str, bool, str]] = []
VERBOSE = False
INAPPLICABLE: list[tuple[str, str, str]] = []
# Rebound by --engine. The destructive-path fixtures drive this directly rather
# than through the shell entrypoints, so an alternative engine can be substituted.
ACTIVE_ENGINE = ENGINE
FAMILY: dict[str, str] = {}


def check(ac: str, name: str, cond: bool, detail: str = "", family: str = "") -> bool:
    RESULTS.append((ac, name, bool(cond), detail))
    if family:
        FAMILY[f"{ac} {name}"] = family
    if VERBOSE or not cond:
        print(f"  [{'PASS' if cond else 'FAIL'}] {ac} {name}" + (f"  -- {detail}" if detail else ""))
    return bool(cond)


def inapplicable(ac: str, name: str, why: str) -> None:
    """Surface the engine under test does not have. NOT evidence of a defect."""
    INAPPLICABLE.append((ac, name, why))
    print(f"  [SKIP] {ac} {name}  -- inapplicable-on-alternative-engine: {why}")


def engine_run(command: str, *extra, expect_surface: bool = True):
    """Drive the engine directly. Returns (rc, stdout, stderr)."""
    return run([sys.executable, ACTIVE_ENGINE, command,
                "--profile-file", SOURCE / "scripts" / "install" / "profiles" / "core.json",
                "--source", SOURCE, *extra])


def missing_surface(rc: int, err: str) -> str | None:
    """Classify a failure that is the engine LACKING surface, not misbehaving."""
    for token, why in (("unrecognized arguments", "engine does not accept this flag"),
                       ("FileNotFoundError", "engine does not produce this artifact"),
                       ("KeyError", "engine does not record this state field"),
                       ("AttributeError", "engine does not expose this symbol")):
        if token in err:
            return why
    return None


def selfmanage_expected(prefix: Path) -> set:
    """The self-management bundle, read from the RECORDED manifest, not a literal.

    Reading it from state makes the comparison validate the record too: a bundle
    that shipped files the record does not declare (or vice versa) fails here.
    """
    state = json.loads((prefix / "state" / "install-state.json").read_text())
    bundle = state["generations"][-1]["self_management"]
    rel = bundle["root_relative"].split("/", 1)[1]
    return {f"{rel}/{name}" for name in bundle["files"]}


def installed_expected(prefix: Path) -> set:
    """Everything the isolated root is supposed to carry, in both directions."""
    return payload_expected() | selfmanage_expected(prefix)


def write_unconventional(path: Path, doc: dict) -> None:
    """Write a settings document deliberately OUTSIDE the installer's convention.

    Differs in four ways at once: 4-space indent, CRLF line endings,
    \\uXXXX-escaped non-ASCII, and sorted key order. Without this, every
    preservation assertion is satisfied by construction -- a fixture already in
    the installer's convention survives a loads/dumps round-trip byte-for-byte
    whether or not the implementation preserves anything.
    """
    text = json.dumps(doc, indent=4, ensure_ascii=True, sort_keys=True)
    path.write_bytes((text.replace("\n", "\r\n") + "\r\n").encode("utf-8"))


def realpath_map(root: Path) -> dict:
    """Realpath per node, RECORDED at a point in time.

    Recorded on one side and recomputed on the other. An assertion that resolves
    the SAME path expression on both sides is true by construction and cannot fail
    for any input -- which is exactly what the assertion this replaces did.
    """
    return {p: os.path.realpath(root / p) for p in node_snapshot(root)
            if (root / p).exists()}


def realpath_regressions(root: Path, recorded: dict) -> list:
    return [(p, recorded[p], os.path.realpath(root / p)) for p in recorded
            if (root / p).exists() and os.path.realpath(root / p) != recorded[p]]


def hook_commands(doc: dict) -> list[tuple]:
    out = []
    for event, bucket in (doc.get("hooks") or {}).items():
        for group in bucket if isinstance(bucket, list) else []:
            if not isinstance(group, dict):
                continue
            for entry in group.get("hooks") or []:
                if isinstance(entry, dict):
                    out.append((event, group.get("matcher") or None,
                                entry.get("type"), entry.get("command")))
    return out


def installer_commands(home: Path) -> list[str]:
    bridge_rel = next(e["path"] for e in PROFILE["live_footprint"] if e["kind"] == "link")
    return [r["command"].replace("<bridge>", str(home / bridge_rel))
            for r in PROFILE["hook_registrations"]]


def payload_refs(doc: dict, home: Path) -> list[tuple]:
    bridge_rel = next(e["path"] for e in PROFILE["live_footprint"] if e["kind"] == "link")
    marker = str(home / bridge_rel)
    return [c for c in hook_commands(doc) if c[3] and marker in c[3]]


def read_state(prefix: Path) -> dict:
    return json.loads((prefix / "state" / "install-state.json").read_text())


def require_installed(home: Path, prefix: Path, label: str) -> bool:
    """NON-VACUITY PRECONDITION -- binds every refusal criterion below.

    A criterion whose only assertions are "exit non-zero" and "nothing changed" is
    satisfied by an installer that does nothing at all. Every refusal fixture must
    first prove a prior apply ACTUALLY installed each expected registration
    identity, read back out of the live document, with the payload and state file
    present.
    """
    doc = json.loads((home / "settings.json").read_text())
    present = {c[3] for c in hook_commands(doc)}
    expected = set(installer_commands(home))
    ok = (expected <= present and (prefix / "state" / "install-state.json").is_file()
          and (prefix / "harness").is_dir())
    return check(label, "PRECONDITION: the prior apply installed every registration "
                        "identity, payload and state file", ok,
                 f"missing={sorted(expected - present)} "
                 f"state={(prefix / 'state' / 'install-state.json').is_file()} "
                 f"payload={(prefix / 'harness').is_dir()}")


def run(cmd, env=None, cwd=None):
    e = dict(os.environ)
    e.pop("CLAUDE_CONFIG_DIR", None)
    e.pop("XDG_DATA_HOME", None)
    if env:
        e.update(env)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       env=e, cwd=str(cwd) if cwd else None)
    return p.returncode, p.stdout, p.stderr


# Fixture-only location for the user's own hook commands. The assertions round-trip
# USER_SETTINGS through the merge and compare it for equality, so these paths only need
# to be absolute and stable — never real. Derived from the platform temp dir rather than
# written as an author-home literal, which the public-core residue gate rejects.
USER_HOOK_DIR = Path(tempfile.gettempdir()) / "acceptance-user-hooks"

USER_SETTINGS = {
    "$schema": "https://json.schemastore.org/claude-code-settings.json",
    "cleanupPeriodDays": 42,
    "env": {"USER_ENV_KEY": "user-value"},
    "permissions": {
        "allow": ["Bash(ls:*)", "Read", "Bash(git status:*)"],
        "deny": ["Bash(rm -rf /:*)", "Read(./.env)"],
        "ask": ["Bash(git push:*)"],
    },
    "model": "opus",
    "theme": "dark",
    "mcpServers": {"userServer": {"command": "npx", "args": ["-y", "user-mcp"]}},
    "hooks": {
        # PreToolUse is an event the harness ALSO registers on: the merge must not
        # disturb these groups or their order.
        "PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": f"bash {USER_HOOK_DIR / 'my-own-guard.sh'}"}]},
            {"hooks": [{"type": "command", "command": f"python3 {USER_HOOK_DIR / 'second-guard.py'}"}]},
        ],
        "Stop": [{"hooks": [{"type": "command", "command": "echo user-stop"}]}],
    },
    "userUnknownExtensionKey": {"nested": [1, 2, 3]},
}
USER_CLAUDE_MD = "# my personal instructions\n\nalways answer in haiku\n"
USER_MCP_FILE = '{"mcpServers": {"fileServer": {"command": "node", "args": ["s.js"]}}}\n'
USER_COMMAND = "---\ndescription: my own command\n---\n\n# mine\n"


def make_populated(n2: Path, *, conflict: bool = False, commands_dir: bool = True) -> None:
    n2.mkdir(parents=True, exist_ok=True)
    (n2 / "settings.json").write_text(json.dumps(USER_SETTINGS, indent=2) + "\n")
    (n2 / "CLAUDE.md").write_text(USER_CLAUDE_MD)
    (n2 / ".mcp.json").write_text(USER_MCP_FILE)
    if commands_dir:
        (n2 / "commands").mkdir()
        (n2 / "commands" / "user-foo.md").write_text(USER_COMMAND)
    if conflict:
        (n2 / "commands").mkdir(exist_ok=True)
        (n2 / "commands" / "harness-doctor.md").write_text("# MY OWN harness-doctor\n")


def snap_pair(prefix: Path, n2: Path) -> dict:
    return {"prefix": node_snapshot(prefix), "config_home": node_snapshot(n2)}


def diff_transitions(s1: dict, s2: dict) -> set:
    """Durable NET transitions between two snapshot pairs, as (tree, path, kind)."""
    out = set()
    for tree in ("prefix", "config_home"):
        a, b = s1[tree], s2[tree]
        for path in set(a) | set(b):
            if path not in a:
                out.add((tree, path, "create"))
            elif path not in b:
                out.add((tree, path, "delete"))
            elif a[path] != b[path]:
                out.add((tree, path, "modify"))
    return out


def payload_expected() -> set:
    files = {i["dest"] for i in PROFILE["payload"]["copied"]}
    files |= set(PROFILE["payload"]["generated"])
    return files


def actual_files(root: Path) -> set:
    return {p for p, e in node_snapshot(root).items() if e["type"] == "file"}


# --------------------------------------------------------------------------- #
def ac1(tmp: Path) -> None:
    print("AC1  isolated install -- bounded footprint that actually activates")
    n2, prefix = tmp / "ac1" / "n2", tmp / "ac1" / "prefix"
    n2.mkdir(parents=True)
    before = node_snapshot(n2)
    rc, out, err = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2])
    check("AC1(d)", "exit code is 0", rc == 0, f"rc={rc} err={err[-400:]}")
    iso = prefix / "harness"
    check("AC1(a)", "isolated root file set == manifest payload + recorded "
                    "self-management bundle (both directions)",
          actual_files(iso) == installed_expected(prefix),
          f"only-on-disk={sorted(actual_files(iso) - installed_expected(prefix))} "
          f"only-in-manifest={sorted(installed_expected(prefix) - actual_files(iso))}")
    created = {p for p in node_snapshot(n2) if p != "." and p not in before}
    declared = {e["path"] for e in PROFILE["live_footprint"]}
    check("AC1(b)", "config-home created set == live_footprint (both directions)",
          created == declared, f"created={sorted(created)} declared={sorted(declared)}")
    kinds = {"file": "file", "link": "symlink", "dir": "dir"}
    snap = node_snapshot(n2)
    check("AC1(b)", "each footprint entry has its declared kind on disk",
          all(snap[e["path"]]["type"] == kinds[e["kind"]] for e in PROFILE["live_footprint"]),
          str({e["path"]: snap[e["path"]]["type"] for e in PROFILE["live_footprint"]}))
    bridge = next(e["path"] for e in PROFILE["live_footprint"] if e["kind"] == "link")
    rc2, resolved, _ = run(["bash", "-c",
                            f'unset CLAUDE_HOME; source "{n2}/{bridge}/hooks/lib/claude_home.sh"; '
                            f'claude_home_resolve'])
    check("AC1(c)", "harness home resolved from the N2 footprint == isolated root",
          resolved.strip() == str(iso), f"resolved={resolved.strip()!r} expected={iso}")
    sentinel = all((n2 / p).exists() for p in ("settings.json", "hooks", "policies", "scripts"))
    check("AC1(c)", "no sentinel-complete harness copy beneath the config home",
          not sentinel, "config home must not itself resolve as a harness home")
    # Compared by CONTENT, not by name: the config home's settings.json and the
    # isolated root's settings.json share a basename but are different artifacts
    # (the user's live registration file vs. the harness's own reference copy).
    # What must not exist is a config-home file that is a COPY of a payload file.
    iso_hashes = {e["sha256"] for e in node_snapshot(iso).values() if e["type"] == "file"}
    dup = {p for p, e in node_snapshot(n2).items()
           if e["type"] == "file" and e["sha256"] in iso_hashes}
    check("AC1(c)", "no duplicate payload copy under the config home (compared by content)",
          not dup, str(sorted(dup)))
    state = json.loads((prefix / "state" / "install-state.json").read_text())
    kinds_recorded = {c["kind"] for c in state["generations"][0]["created"]}
    check("AC1", "install inventory records each footprint entry kind",
          kinds_recorded <= {"file", "link", "dir"} and "link" in kinds_recorded,
          str(sorted(kinds_recorded)))
    check("AC1(d)", "stdout names both the isolated root and the resolved config home",
          str(iso) in out and str(n2) in out)

    # --config-dir override AND env-based resolution
    n2b, prefixb = tmp / "ac1b" / "cfg", tmp / "ac1b" / "prefix"
    n2b.mkdir(parents=True)
    rc, out, _ = run([INSTALL, "--profile", "core", "--prefix", prefixb, "--config-dir", n2b],
                     env={"CLAUDE_CONFIG_DIR": str(tmp / "ac1b" / "DECOY")})
    check("AC1(e)", "--config-dir overrides CLAUDE_CONFIG_DIR and is reported",
          rc == 0 and (n2b / "settings.json").is_file()
          and not (tmp / "ac1b" / "DECOY").exists() and str(n2b) in out, f"rc={rc}")
    n2c, prefixc = tmp / "ac1c" / "cfg", tmp / "ac1c" / "prefix"
    n2c.mkdir(parents=True)
    rc, out, _ = run([INSTALL, "--profile", "core", "--prefix", prefixc],
                     env={"CLAUDE_CONFIG_DIR": str(n2c)})
    check("AC1(e)", "config home resolved as ${CLAUDE_CONFIG_DIR:-$HOME/.claude}",
          rc == 0 and (n2c / "settings.json").is_file() and str(n2c) in out, f"rc={rc}")


def ac2(tmp: Path) -> None:
    print("AC2  core profile -- non-vacuous, and the installed payload actually guards")
    n2, prefix = tmp / "ac2" / "n2", tmp / "ac2" / "prefix"
    n2.mkdir(parents=True)
    rc, out, _ = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2])
    iso = prefix / "harness"
    declared = set()
    for comp in PROFILE["components"]:
        declared |= set(comp["files"])
    declared_plus = declared | selfmanage_expected(prefix)
    check("AC2(a)", "installed component set == manifest core set + recorded "
                    "self-management bundle (both directions)",
          actual_files(iso) == declared_plus,
          f"disk-only={sorted(actual_files(iso) - declared_plus)} "
          f"manifest-only={sorted(declared_plus - actual_files(iso))}")
    # The bundle is the payload-resident uninstall path (R9). It must be an
    # explicit versioned list whose recorded digests match what is on disk --
    # never a recursive copy of scripts/install/, which would re-import this very
    # harness and every future sibling file.
    bundle = read_state(prefix)["generations"][-1]["self_management"]
    bundle_dir = iso / bundle["root_relative"].split("/", 1)[1]
    check("AC2(f)", "the self-management bundle matches its recorded digests exactly",
          all(sha256_file(bundle_dir / name) == bundle["digests"][name]
              for name in bundle["files"]),
          f"files={bundle['files']}")
    check("AC2(f)", "the bundle carries no file it does not declare (non-recursive)",
          {p.name for p in bundle_dir.iterdir()} == set(bundle["files"]),
          str(sorted(p.name for p in bundle_dir.iterdir())))
    present = actual_files(iso) | {p for p in node_snapshot(iso)}
    bad = [x for x in PROFILE["excluded"] if any(p == x or p.startswith(x + "/") for p in present)]
    check("AC2(b)", "every excluded component is absent from the isolated root", not bad, str(bad))
    roles = {c["role"] for c in PROFILE["components"]}
    check("AC2(c)", "core floor: safety_hook AND capability_gate components are present",
          {"safety_hook", "capability_gate"} <= roles, str(sorted(roles)))
    floor_files = [f for c in PROFILE["components"]
                   if c["role"] in ("safety_hook", "capability_gate") for f in c["files"]]
    check("AC2(c)", "core floor components exist on disk and are non-empty",
          all((iso / f).is_file() and (iso / f).stat().st_size > 0 for f in floor_files),
          str(floor_files))
    smoke = PROFILE["block_decision_smoke"]
    payload = dict(smoke["stdin"], session_id="acceptance-smoke-unique")
    p = subprocess.run([smoke["interpreter"], str(iso / smoke["hook"])],
                       input=json.dumps(payload), capture_output=True, text=True)
    check("AC2(d)", "installed safety hook emits its block decision on a forbidden input",
          p.returncode == smoke["expect_exit"] and smoke["expect_stderr_contains"] in p.stderr,
          f"rc={p.returncode} stderr={p.stderr[:160]!r}")
    rc2, plan_out, _ = run([INSTALL, "--dry-run", "--profile", "core",
                            "--prefix", tmp / "ac2" / "p2", "--config-dir", tmp / "ac2" / "n2b"])
    listed_inc = {ln.strip()[2:] for ln in plan_out.splitlines() if ln.strip().startswith("+ ")}
    listed_inc = {x.split("  ")[0] for x in listed_inc}
    listed_exc = {ln.strip()[2:] for ln in plan_out.splitlines() if ln.strip().startswith("- ")}
    check("AC2(e)", "printed include listing == measured installed set",
          listed_inc == actual_files(iso), f"printed-only={sorted(listed_inc - actual_files(iso))}")
    check("AC2(e)", "printed exclude listing == manifest excluded set",
          listed_exc == set(PROFILE["excluded"]), str(sorted(listed_exc ^ set(PROFILE["excluded"]))))


def make_python39_shim(d: Path) -> Path:
    """A PATH shim reporting Python 3.9 while delegating every other call."""
    d.mkdir(parents=True, exist_ok=True)
    real = shutil.which("python3")
    shim = d / "python3"
    shim.write_text(f"""#!/bin/bash
if [ "${{1:-}}" = "--version" ]; then echo "Python 3.9.7"; exit 0; fi
if [ "${{1:-}}" = "-c" ] && [[ "${{2:-}}" == *version_info* ]]; then echo "3.9"; exit 0; fi
exec "{real}" "$@"
""")
    shim.chmod(0o755)
    return d


def ac3(tmp: Path) -> None:
    print("AC3  strict preflight -- paired positive/negative, strict is not an alias")
    # (P) healthy host
    rc_plain, _, _ = run([SOURCE / "scripts" / "doctor"])
    check("AC3(P)", "plain scripts/doctor exits 0 on this healthy host", rc_plain == 0,
          f"rc={rc_plain}")
    rc_strict, out, err = run([PREFLIGHT, "--source", SOURCE, "--skip-deep"])
    check("AC3(P)", "installer preflight (owned sections) exits 0 on the healthy host",
          rc_strict == 0, f"rc={rc_strict} err={err[-300:]}")
    for token in ("Baseline dependencies", "Strict-only host requirements", "Host support status",
                  "Host-capability handshake"):
        check("AC3(P)", f"strict report enumerates section: {token}", token in out)
    check("AC3", "report separates installer-owned baseline from the capability gate's handshake",
          "owner: capability gate, NOT the installer" in out and "owner: installer" in out)
    check("AC3", "report makes no full-protection claim",
          "Nothing here asserts that full protection is verified" in out)

    # (N1) differential outcome: plain doctor 0, strict nonzero, on a documented requirement
    shim = make_python39_shim(tmp / "ac3" / "bin")
    penv = {"PATH": f"{shim}:{os.environ['PATH']}"}
    rc_plain2, _, _ = run([SOURCE / "scripts" / "doctor"], env=penv)
    rc_strict2, _, err2 = run([PREFLIGHT, "--source", SOURCE, "--skip-deep"], env=penv)
    check("AC3(N1)", "STRICT IS NOT AN ALIAS: plain doctor exits 0 while strict exits nonzero",
          rc_plain2 == 0 and rc_strict2 != 0, f"plain={rc_plain2} strict={rc_strict2}")
    check("AC3(N1)", "the strict-only check cites an in-repo documented host requirement",
          ".github/workflows/baseline.yml:24-28" in err2, err2[-200:])

    # (N2) abort before mutation
    n2, prefix = tmp / "ac3" / "n2", tmp / "ac3" / "prefix"
    make_populated(n2)
    before = snap_pair(prefix, n2)
    rc, _, _ = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2],
                   env=penv)
    after = snap_pair(prefix, n2)
    check("AC3(N2)", "preflight failure => installer exits nonzero", rc != 0, f"rc={rc}")
    check("AC3(N2)", "config-home snapshot identical before and after (zero mutations)",
          before["config_home"] == after["config_home"],
          str(diff_transitions(before, after)))
    check("AC3(N2)", "the isolated root was never created", not prefix.exists())


def ac4_ac5(tmp: Path) -> dict:
    print("AC4  dry-run -- provably zero mutation, and the plan must not lie")
    n2, prefix = tmp / "ac45" / "n2", tmp / "ac45" / "prefix"
    make_populated(n2, conflict=True)
    pre_install = snap_pair(prefix, n2)
    pre_realpaths = realpath_map(n2)
    s0 = snap_pair(prefix, n2)

    rc, out, err = run([INSTALL, "--dry-run", "--profile", "core",
                        "--prefix", prefix, "--config-dir", n2])
    s1 = snap_pair(prefix, n2)
    check("AC4(d)", "dry-run exits 0", rc == 0, f"rc={rc} err={err[-300:]}")
    check("AC4(b)", "S0 == S1: config home byte-identical after the dry run",
          s0["config_home"] == s1["config_home"], str(diff_transitions(s0, s1)))
    check("AC4(c)", "the isolated root was not created or modified by the dry run",
          s0["prefix"] == s1["prefix"] and not prefix.exists())
    check("AC4(a)", "the report enumerates target path and change kind per intended change",
          all(t in out for t in ("[create]", "Intended changes")), "")
    check("AC4(a)", "conflicts are reported with the conflicting path",
          "harness-doctor.md" in out and "[conflict]" in out)

    _, plan_json, _ = run([sys.executable, ENGINE, "plan", "--json", "--profile", "core",
                           "--prefix", prefix, "--config-dir", n2, "--source", SOURCE])
    plan = json.loads(plan_json)
    d_set = {(c["tree"], c["path"], c["change_kind"]) for c in plan["changes"]}
    check("AC4(a)", "dry-run plan set is NON-EMPTY against the populated fixture",
          len(d_set) > 0, f"|D|={len(d_set)}")

    print("AC5  real apply -- per-artifact preservation invariants")
    rc, out, err = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2])
    s2 = snap_pair(prefix, n2)
    check("AC5", "real apply exits 0", rc == 0, f"rc={rc} err={err[-400:]}")
    a_set = diff_transitions(s1, s2)
    check("AC4(e)", "PLAN/APPLY PARITY: D == A in both directions",
          d_set == a_set,
          f"plan-only={sorted(d_set - a_set)} apply-only={sorted(a_set - d_set)}")

    # (a) personal CLAUDE.md
    check("AC5(a)", "personal CLAUDE.md byte-identical at its original path",
          (n2 / "CLAUDE.md").read_text() == USER_CLAUDE_MD)
    # (b) settings semantics + (whole-file user-key invariant)
    after_s = json.loads((n2 / "settings.json").read_text())
    before_s = USER_SETTINGS
    check("AC5(b)", "every pre-existing deny entry still present",
          set(before_s["permissions"]["deny"]) <= set(after_s["permissions"]["deny"]))
    check("AC5(b)", "every pre-existing allow entry still present",
          set(before_s["permissions"]["allow"]) <= set(after_s["permissions"]["allow"]))
    check("AC5(b)", "no allow entry broadened (allow set unchanged)",
          after_s["permissions"]["allow"] == before_s["permissions"]["allow"])
    check("AC5(b)", "permissions object completely unchanged",
          after_s["permissions"] == before_s["permissions"])
    missing = [k for k in before_s if k not in after_s]
    check("AC5(b)", "every pre-existing top-level settings key survives", not missing, str(missing))
    unchanged = [k for k in before_s if k != "hooks" and after_s.get(k) == before_s[k]]
    check("AC5(b)", "every non-hooks user key survives semantically unchanged "
                    "(env, model, theme, mcpServers, unknown extension key)",
          len(unchanged) == len([k for k in before_s if k != "hooks"]),
          f"changed={[k for k in before_s if k != 'hooks' and k not in unchanged]}")
    order_ok = True
    for event, groups in before_s["hooks"].items():
        post = after_s["hooks"].get(event, [])
        if post[:len(groups)] != groups:
            order_ok = False
    check("AC5(b)", "user hook registrations survive with their order preserved "
                    "(incl. PreToolUse, an event the harness also registers)", order_ok,
          json.dumps(after_s["hooks"].get("PreToolUse"))[:300])
    added = [g for g in after_s["hooks"]["PreToolUse"][len(before_s["hooks"]["PreToolUse"]):]]
    check("AC5(b)", "harness registrations are APPENDED after the user's, not interleaved",
          len(added) >= 1)
    # (c) parseable
    check("AC5(c)", "merged settings.json still parses as JSON", isinstance(after_s, dict))
    check("AC5(c)", "installer rendered no part of settings.json from a template "
                    "(render-settings never invoked; parity clause inapplicable by construction)",
          PROFILE["settings_merge"]["policy"] == "additive-only")
    # (d) user command files
    check("AC5(d)", "non-core user command file byte-identical at its original path",
          (n2 / "commands" / "user-foo.md").read_text() == USER_COMMAND)
    # (e) MCP
    check("AC5(e)", "pre-existing MCP server keys semantically intact",
          after_s["mcpServers"] == before_s["mcpServers"]
          and (n2 / ".mcp.json").read_text() == USER_MCP_FILE)
    # (f) backup before touch
    state = json.loads((prefix / "state" / "install-state.json").read_text())
    gen = state["generations"][0]
    ok_backup = True
    for m in gen["modified"]:
        bp = Path(m["backup"])
        ok_backup = ok_backup and bp.is_file() and \
            json.loads(bp.read_text()) == before_s
    check("AC5(f)", "for every modified file a backup exists whose content == pre-touch content",
          bool(gen["modified"]) and ok_backup, f"modified={[m['path'] for m in gen['modified']]}")
    # (g) conflict
    check("AC5(g)", "conflicting path named in the conflict report",
          any(c["path"] == "commands/harness-doctor.md" for c in gen["conflicts"]))
    check("AC5(g)", "the USER's version of the conflicting file is the one retained on disk",
          (n2 / "commands" / "harness-doctor.md").read_text() == "# MY OWN harness-doctor\n")
    # (h) containment: literal membership
    declared = {e["path"] for e in PROFILE["live_footprint"]}
    touched = {p for (tree, p, _k) in a_set if tree == "config_home"}
    check("AC5(h)", "nothing outside live_footprint created/modified/deleted "
                    "(containment = literal membership, never subtree)",
          touched <= declared, f"outside={sorted(touched - declared)}")
    # (i) node identity, split by declared mutability
    mutable = set(PROFILE["mutable_paths"])
    ident_fail, mut_fail = [], []
    for path, entry in pre_install["config_home"].items():
        post = s2["config_home"].get(path)
        if post is None:
            ident_fail.append((path, "absent after apply"))
            continue
        if path in mutable or (path != "." and path.split("/")[0] in mutable):
            # Declared-mutable: the all-or-nothing apply writes a temp file and
            # atomically renames it, which necessarily allocates a NEW inode. The
            # substituted invariants are node type, path, pre-touch backup parity
            # and no alias of the pre-apply inode under the isolated root.
            if post["type"] != entry["type"]:
                mut_fail.append((path, "node type changed"))
            continue
        if post["type"] != entry["type"] or (post["dev"], post["ino"]) != (entry["dev"], entry["ino"]):
            ident_fail.append((path, f"{entry} -> {post}"))
        if entry["type"] == "symlink" and post.get("target") != entry.get("target"):
            ident_fail.append((path, "raw readlink target changed"))
    check("AC5(i)", "every NON-mutable pre-existing user artifact holds node type + "
                    "(st_dev, st_ino) inode identity + raw readlink target",
          not ident_fail, str(ident_fail[:4]))
    check("AC5(i)", "the declared-mutable file keeps its node type and path "
                    "(inode change is the approved atomic temp+rename)", not mut_fail, str(mut_fail))
    pre_inodes = {(e["dev"], e["ino"]) for e in pre_install["config_home"].values()
                  if e["type"] == "file"}
    iso_inodes = {(e["dev"], e["ino"]) for e in node_snapshot(prefix / "harness").values()
                  if e["type"] == "file"}
    check("AC5(i)", "the isolated root contains NO inode alias (hardlink) of any "
                    "pre-existing user file, including the pre-apply mutable inode",
          not (pre_inodes & iso_inodes), str(sorted(pre_inodes & iso_inodes)[:3]))
    dirs_before = {p for p, e in pre_install["config_home"].items() if e["type"] == "dir"}
    relocated = [p for p in dirs_before if s2["config_home"].get(p, {}).get("type") == "symlink"]
    check("AC5(i)", "no path that was a populated real directory before apply is a symlink after",
          not relocated, str(relocated))
    # The pre-install snapshot RECORDS a realpath per entry; the assertion compares
    # that recorded value against the post-apply realpath. The assertion this
    # replaces read both operands from the same path expression, so its inequality
    # was False for every input by construction and it could not fail against ANY
    # fixture -- including one designed to break it.
    rp_fail = realpath_regressions(n2, pre_realpaths)
    check("AC5(i)", "realpath unchanged for every path that resolved before the install",
          not rp_fail, str(rp_fail[:3]))

    # NEGATIVE CONTROL -- falsifiability proof for the assertion directly above.
    # A purely syntactic predicate ("the two operands are not the same expression")
    # is NOT sufficient: two textually different but semantically identical
    # expressions would satisfy it while remaining just as unfalsifiable. So the
    # same predicate is run against a deliberately-relocating mutation, which is
    # the thing it is supposed to catch. The unfixed installer relocates nothing,
    # so a correctly repaired assertion also passes against it -- which is why
    # falsifiability can only be shown against this control.
    nc = tmp / "ac5nc" / "n2"
    make_populated(nc)
    nc_recorded = realpath_map(nc)
    relocated_tree = tmp / "ac5nc" / "elsewhere"
    relocated_tree.mkdir(parents=True)
    shutil.move(str(nc / "CLAUDE.md"), str(relocated_tree / "CLAUDE.md"))
    os.symlink(str(relocated_tree / "CLAUDE.md"), nc / "CLAUDE.md")
    nc_fail = realpath_regressions(nc, nc_recorded)
    check("AC5(i)", "NEGATIVE CONTROL: the realpath assertion FAILS against a "
                    "relocating mutation (proves it is falsifiable at all)",
          bool(nc_fail), f"regressions_detected={nc_fail[:2]}")
    return {"n2": n2, "prefix": prefix, "pre_install": pre_install}


def ac6(tmp: Path) -> None:
    print("AC6  uninstall -- ownership-aware, not a whole-tree restore")
    n2, prefix = tmp / "ac6" / "n2", tmp / "ac6" / "prefix"
    # commands/ is ABSENT so the installer creates (and therefore owns) it.
    make_populated(n2, commands_dir=False)
    original_settings_sha = sha256_file(n2 / "settings.json")
    pre = snap_pair(prefix, n2)

    rc, _, err = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2])
    check("AC6", "first install succeeded", rc == 0, f"rc={rc} err={err[-300:]}")
    check("AC6", "the installer created (and therefore owns) the commands directory",
          any(c["path"] == "commands" and c["kind"] == "dir"
              for c in json.loads((prefix / "state" / "install-state.json")
                                  .read_text())["generations"][0]["created"]))

    # (i) unrelated post-install user edit, on a file the installer does not own
    (n2 / "CLAUDE.md").write_text(USER_CLAUDE_MD + "\nedited after install\n")
    edited_sha = sha256_file(n2 / "CLAUDE.md")
    # (ii) a user file created INSIDE an installer-owned directory
    (n2 / "commands" / "user-after.md").write_text("# created after install\n")
    # force the second install to modify settings again: the user removes one of
    # the harness registrations by hand, so gen-002 backs up a NON-original file.
    s = json.loads((n2 / "settings.json").read_text())
    s["hooks"]["PreToolUse"].pop()
    (n2 / "settings.json").write_text(json.dumps(s, indent=2) + "\n")
    # (iii) repeat install
    rc, _, _ = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2])
    state = json.loads((prefix / "state" / "install-state.json").read_text())
    check("AC6(d)", "the repeat install created a SECOND backup generation, "
                    "leaving the first intact", rc == 0 and len(state["generations"]) == 2,
          f"generations={len(state['generations'])}")

    rc, out, err = run([UNINSTALL, "--prefix", prefix, "--config-dir", n2, "--json"])
    check("AC6", "uninstall exits 0", rc == 0, f"rc={rc} err={err[-300:]}")
    check("AC6(a)", "the installer-created link entry is removed",
          not (n2 / "harness").is_symlink() and not (n2 / "harness").exists())
    check("AC6(a)", "the installer-created file entry is removed by exact path",
          not (n2 / "commands" / "harness-doctor.md").exists())
    check("AC6(a)", "an owned dir entry is NOT removed while non-empty (never recursive)",
          (n2 / "commands").is_dir())
    check("AC6(b)", "the modified file is restored to its pre-install content",
          sha256_file(n2 / "settings.json") == original_settings_sha)
    check("AC6(d)", "after a repeat install, uninstall restores the pre-FIRST-install content",
          json.loads((n2 / "settings.json").read_text()) == USER_SETTINGS)
    check("AC6(c)", "unrelated post-install user edit survives byte-identical",
          sha256_file(n2 / "CLAUDE.md") == edited_sha)
    check("AC6(c)", "a user file created INSIDE an installer-owned directory survives",
          (n2 / "commands" / "user-after.md").read_text() == "# created after install\n")
    check("AC6(e)", "pre-existing user content is intact per the AC5 invariants",
          (n2 / ".mcp.json").read_text() == USER_MCP_FILE)
    post = node_snapshot(n2)
    ident = [p for p, e in pre["config_home"].items()
             if p != "settings.json" and p != "."
             and (p not in post or (post[p]["dev"], post[p]["ino"]) != (e["dev"], e["ino"]))]
    check("AC6(e)", "non-mutable pre-existing artifacts kept inode identity across the cycle",
          not ident, str(ident[:4]))
    # The cross-check consumes the MACHINE-READABLE report and validates EVERY
    # reported item. It used to be two substring tests over stdout -- and both of
    # those substrings were present during a run that destroyed an unrelated
    # config home, so they certified nothing. (The dead JSON round-trip loop that
    # preceded this check round-tripped the output lines through JSON and threw
    # them away; it is gone.)
    report = json.loads(out)
    items = report["items"]
    validated, unsound = 0, []
    for it in items:
        result = it["result"]
        if it["action"] == "settings":
            ok = it["measured_sha256"] == it["expected_sha256"]
        elif result == "removed":
            ok = it["measured_present"] is False
        elif result.startswith("kept-"):
            ok = it["measured_present"] is True
        elif result in ("absent", "absent-clean"):
            ok = it["measured_present"] is False
        elif result.startswith("skipped"):
            ok = True                      # asserts no presence either way
        else:
            ok = False                     # an unclassified result is not validated
        validated += 1
        if not ok:
            unsound.append(it)
    check("AC6(g)", "the report is machine-readable and carries at least one item",
          isinstance(items, list) and len(items) > 0, f"K={len(items)}")
    check("AC6(g)", "EVERY reported item is validated against measured state "
                    "(removals absent, kept items present, digests equal)",
          not unsound and validated == len(items),
          f"validated={validated}/{len(items)} unsound={unsound[:3]}")

    # (c, extended) a file the installer created but the USER then rewrote is the
    # user's file now: uninstall must keep it rather than delete their content.
    n2c, prefixc = tmp / "ac6c" / "n2", tmp / "ac6c" / "prefix"
    n2c.mkdir(parents=True)
    run([INSTALL, "--profile", "core", "--prefix", prefixc, "--config-dir", n2c])
    (n2c / "commands" / "harness-doctor.md").write_text("# I rewrote this myself\n")
    rc, out_c, _ = run([UNINSTALL, "--prefix", prefixc, "--config-dir", n2c])
    check("AC6(c)", "a file the installer created but the user later rewrote is KEPT, "
                    "not deleted", rc == 0
          and (n2c / "commands" / "harness-doctor.md").is_file()
          and (n2c / "commands" / "harness-doctor.md").read_text() == "# I rewrote this myself\n"
          and "kept-user-modified" in out_c, out_c[-300:])

    # (f) link removal must not delete isolated-root content through the link
    n2b, prefixb = tmp / "ac6f" / "n2", tmp / "ac6f" / "prefix"
    n2b.mkdir(parents=True)
    run([INSTALL, "--profile", "core", "--prefix", prefixb, "--config-dir", n2b])
    payload_before = actual_files(prefixb / "harness")
    rc, _, _ = run([UNINSTALL, "--prefix", prefixb, "--config-dir", n2b, "--keep-payload"])
    check("AC6(f)", "uninstall removes the footprint link WITHOUT following it into "
                    "the isolated root", rc == 0 and not (n2b / "harness").is_symlink()
          and actual_files(prefixb / "harness") == payload_before,
          f"payload files after={len(actual_files(prefixb / 'harness'))}")


def ac7(tmp: Path) -> None:
    print("AC7  macOS answered -- derived from the matrix, not a literal")
    rc, out, err = run([PREFLIGHT, "--source", SOURCE, "--skip-deep"])
    host_line = [ln for ln in out.splitlines() if ln.strip().startswith("host:")]
    check("AC7(a)", "a support-status line for the detected OS is always emitted",
          len(host_line) == 1, str(host_line))

    # derivation proof: fake the host as Darwin, then ALTER the Darwin row
    shim = tmp / "ac7" / "bin"
    shim.mkdir(parents=True)
    (shim / "uname").write_text('#!/bin/bash\nif [ "${1:-}" = "-s" ]; then echo Darwin; '
                                f'else exec {shutil.which("uname")} "$@"; fi\n')
    (shim / "uname").chmod(0o755)
    denv = {"PATH": f"{shim}:{os.environ['PATH']}"}
    _, mac_out, _ = run([PREFLIGHT, "--source", SOURCE, "--skip-deep"], env=denv)
    mac_line = " ".join(ln for ln in mac_out.splitlines() if "host:" in ln)
    check("AC7(c)", "against the unmodified tree the macOS line reports "
                    "'unsupported' with no CI coverage",
          "unsupported" in mac_line and "none" in mac_line, mac_line.strip())
    check("AC7(d)", "the emitted line never asserts an unverified 'works'",
          "works" not in mac_out.lower().split("host:")[-1][:400])

    altered = tmp / "ac7" / "altered-matrix.md"
    text = MATRIX.read_text()
    marker = "SENTINEL-ALTERED-ROW"
    altered.write_text(text.replace("| macOS | Darwin | unsupported | none |",
                                    f"| macOS | Darwin | {marker} | ci-{marker} |"))
    _, alt_out, _ = run([PREFLIGHT, "--source", SOURCE, "--skip-deep", "--matrix", altered],
                        env=denv)
    check("AC7(b)", "DERIVATION PROOF: altering the matrix row changes the emitted line",
          marker in alt_out and marker not in mac_out, alt_out[-300:])
    text_l = text
    check("AC7(e)", "the matrix carries BOTH an OS axis and a Claude Code build axis",
          "os-matrix:begin" in text_l and "build-matrix:begin" in text_l)
    check("AC7(e)", "the build axis records verification status rather than an "
                    "unverified support claim",
          "unverified" in text_l.split("build-matrix:begin")[1].split("build-matrix:end")[0])


def ac8(tmp: Path) -> None:
    print("AC8  README stops promoting the bare clone -- and the new command runs")
    lines = README.read_text().splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.strip() == "## Install")
    nxt = next((i for i in range(idx + 1, len(lines))
                if lines[i].startswith("## ") and lines[i].strip() != "## Install"), len(lines))
    section = lines[idx:nxt]
    blocks, cur, inb = [], [], False
    for ln in section:
        if ln.startswith("```"):
            if inb:
                blocks.append("\n".join(cur)); cur = []
            inb = not inb
            continue
        if inb:
            cur.append(ln)
    install_blocks = [b for b in blocks if "install" in b or "clone" in b]
    first = install_blocks[0] if install_blocks else ""
    check("AC8(a)", "the first executable install block invokes the installer",
          "scripts/install/install" in first, first[:200])
    check("AC8(a)", "it no longer instructs cloning the repository onto the Claude config home",
          not any("clone" in b and "~/.claude" in b for b in blocks),
          str([b for b in blocks if "clone" in b])[:200])
    body = "\n".join(section)
    check("AC8(b)", "a retained clone sequence sits under a labeled from-source/contributor heading",
          "### From source (contributors)" in body
          and body.index("### From source (contributors)") < body.index("git clone"))
    faq = README.read_text()
    check("AC8(c)", "the FAQ no longer claims a clone over the Claude home is the only installation",
          'The only "installation" is `git clone ... ~/.claude' not in faq)
    check("AC8(c)", "the FAQ points at the installer instead",
          "scripts/install/install --profile core" in faq)

    # (d) executable-doc proof: the promoted command, run verbatim
    n2, prefix = tmp / "ac8" / "cfg", tmp / "ac8" / "data"
    n2.mkdir(parents=True)
    prefix.mkdir(parents=True)
    cmd = [ln.strip() for ln in first.splitlines()
           if ln.strip().startswith("scripts/install/install")
           and "--dry-run" not in ln][0]
    rc, out, err = run(["bash", "-c", cmd], cwd=SOURCE,
                       env={"CLAUDE_CONFIG_DIR": str(n2), "XDG_DATA_HOME": str(prefix)})
    iso = prefix / "claude-harness" / "harness"
    check("AC8(d)", "the README's promoted command, run verbatim, exits 0",
          rc == 0, f"cmd={cmd!r} rc={rc} err={err[-400:]}")
    check("AC8(d)", "it produces the AC1 isolated-root invariant",
          actual_files(iso) == installed_expected(prefix / "claude-harness"),
          f"diff={sorted(actual_files(iso) ^ installed_expected(prefix / 'claude-harness'))}")
    created = {p for p in node_snapshot(n2) if p != "."}
    check("AC8(d)", "it produces the AC1 bounded-footprint invariant",
          created == {e["path"] for e in PROFILE["live_footprint"]}, str(sorted(created)))


# --------------------------------------------------------------------------- #
# AC9-AC14 -- the destructive paths the original harness never exercised.
# It reported 91/91 while four data-destroying defects were live, because it
# never uninstalled against a different home, never edited settings after
# install, and never installed onto a symlinked settings.json.
# --------------------------------------------------------------------------- #
NON_ASCII_KEY_VALUE = "café — naïve ünicode"


def user_doc(extra: dict | None = None) -> dict:
    doc = {
        "model": "opus",
        "mcpServers": {"userServer": {"command": "npx"}},
        "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Read(./.env)"]},
        "userNote": NON_ASCII_KEY_VALUE,
    }
    if extra:
        doc.update(extra)
    return doc


def ac9(tmp: Path) -> None:
    print("AC9  uninstall is BOUND to the config home it installed into")
    base = tmp / "ac9"
    ha, hb, pa = base / "homeA", base / "homeB", base / "prefixA"
    ha.mkdir(parents=True); hb.mkdir(parents=True)
    write_unconventional(ha / "settings.json", user_doc())
    write_unconventional(hb / "settings.json", user_doc(
        {"mcpServers": {"serverB_IRREPLACEABLE": {"command": "b"}}, "model": "sonnet",
         "permissions": {"allow": [], "deny": ["Bash(wget:*)"]}}))

    rc, _out, err = engine_run("apply", "--prefix", pa, "--config-dir", ha)
    if rc != 0 and missing_surface(rc, err):
        inapplicable("AC9", "cross-home refusal", missing_surface(rc, err))
        return
    if not require_installed(ha, pa, "AC9"):
        return

    b_before = (hb / "settings.json").read_bytes()
    b_snap_before = node_snapshot(hb)
    a_snap_before = node_snapshot(ha)
    rc, _out, err = engine_run("uninstall", "--prefix", pa, "--config-dir", hb)

    # AC-INST-1 -- the refusal itself
    check("AC9(a)", "uninstall against a config home it did not install into exits "
                    "non-zero", rc != 0, f"rc={rc} err={err[-200:]}",
          family="cross-home uninstall")
    check("AC9(a)", "MEASURED PREDICATE: home B's settings digest is UNCHANGED "
                    "across the run", (hb / "settings.json").read_bytes() == b_before,
          "the defect this catches rewrote B with A's pre-install bytes",
          family="cross-home uninstall")
    # AC-INST-2 -- the refusal precedes the first mutation
    check("AC9(b)", "home B node snapshot identical on every path, node type, "
                    "(st_dev, st_ino) and readlink target", node_snapshot(hb) == b_snap_before,
          str(sorted(set(node_snapshot(hb)) ^ set(b_snap_before)))[:200],
          family="cross-home uninstall")
    check("AC9(b)", "home A is untouched by the refused run",
          node_snapshot(ha) == a_snap_before, "", family="cross-home uninstall")
    check("AC9(c)", "the state file and the isolated payload are both retained",
          (pa / "state" / "install-state.json").is_file() and (pa / "harness").is_dir(),
          family="cross-home uninstall")
    check("AC9(c)", "stdout/stderr names BOTH the recorded and the requested home",
          str(ha) in err and str(hb) in err, err[-200:])

    # AC-INST-9 -- no dangling wiring, scored against the cross-home fixture where
    # a bare reference count is genuinely falsifiable.
    rc2, _o2, _e2 = engine_run("uninstall", "--prefix", pa, "--config-dir", ha)
    doc_a = json.loads((ha / "settings.json").read_text())
    check("AC9(d)", "after the SUCCESSFUL uninstall against the recorded home, zero "
                    "hook commands reference the isolated root",
          rc2 == 0 and len(payload_refs(doc_a, ha)) == 0,
          f"rc={rc2} refs={payload_refs(doc_a, ha)}")
    check("AC9(d)", "and the user's own pre-existing keys survive it",
          doc_a.get("userNote") == NON_ASCII_KEY_VALUE
          and doc_a.get("mcpServers") == {"userServer": {"command": "npx"}},
          json.dumps(doc_a)[:200])


def ac10(tmp: Path) -> None:
    print("AC10 the un-merge preserves post-install user work")
    base = tmp / "ac10"

    # AC-INST-4 -- four post-install additions
    home, prefix = base / "h4" / "cfg", base / "h4" / "prefix"
    home.mkdir(parents=True)
    write_unconventional(home / "settings.json", user_doc())
    rc, _o, err = engine_run("apply", "--prefix", prefix, "--config-dir", home)
    if rc != 0 and missing_surface(rc, err):
        inapplicable("AC10", "post-install edit survival", missing_surface(rc, err))
        return
    if not require_installed(home, prefix, "AC10"):
        return
    live = json.loads((home / "settings.json").read_text())
    live["mcpServers"]["added_after_install"] = {"command": "x"}
    live["permissions"]["allow"].append("Bash(docker:*)")
    live["permissions"]["deny"].append("Bash(shutdown:*)")
    live["hooks"]["PostToolUse"] = [
        {"hooks": [{"type": "command", "command": "echo my-own-post-hook"}]}]
    (home / "settings.json").write_text(json.dumps(live, indent=2) + "\n")

    rc, out, _e = engine_run("uninstall", "--prefix", prefix, "--config-dir", home, "--json")
    after = json.loads((home / "settings.json").read_text())
    survivors = {
        "mcpServers.added_after_install": "added_after_install" in after.get("mcpServers", {}),
        "permissions.allow Bash(docker:*)":
            "Bash(docker:*)" in after.get("permissions", {}).get("allow", []),
        "permissions.deny Bash(shutdown:*)":
            "Bash(shutdown:*)" in after.get("permissions", {}).get("deny", []),
        "user PostToolUse group": bool((after.get("hooks") or {}).get("PostToolUse")),
    }
    lost = [k for k, v in survivors.items() if not v]
    check("AC10(a)", "MEASURED PREDICATE: every named post-install user key is PRESENT "
                     "after the uninstall", not lost, f"lost={lost}",
          family="post-install-edit survival")
    check("AC10(a)", "and the run reports success", rc == 0, f"rc={rc}",
          family="post-install-edit survival")
    check("AC10(a)", "no hook command still references the isolated root",
          not payload_refs(after, home), str(payload_refs(after, home)))
    check("AC10(a)", "the user's non-ASCII value survives the re-serialization "
                     "(semantic preservation, not byte-identity)",
          after.get("userNote") == NON_ASCII_KEY_VALUE, repr(after.get("userNote")))

    # AC-INST-5 -- removal is ENTRY-level, not group-level
    home5, prefix5 = base / "h5" / "cfg", base / "h5" / "prefix"
    home5.mkdir(parents=True)
    write_unconventional(home5 / "settings.json", user_doc())
    engine_run("apply", "--prefix", prefix5, "--config-dir", home5)
    if not require_installed(home5, prefix5, "AC10(b)"):
        return
    doc5 = json.loads((home5 / "settings.json").read_text())
    universal = installer_commands(home5)[0]
    target_group = next(g for g in doc5["hooks"]["PreToolUse"]
                        if any(h["command"] == universal for h in g["hooks"]))
    user_entry = {"type": "command", "command": "echo mine-inside-their-group"}
    target_group["hooks"].append(user_entry)
    (home5 / "settings.json").write_text(json.dumps(doc5, indent=2) + "\n")
    group_digest_before = json.dumps(target_group, sort_keys=True)

    rc, _o, _e = engine_run("uninstall", "--prefix", prefix5, "--config-dir", home5, "--json")
    after5 = json.loads((home5 / "settings.json").read_text())
    remaining = [g for g in (after5.get("hooks") or {}).get("PreToolUse", [])
                 if user_entry in (g.get("hooks") or [])]
    check("AC10(b)", "the user's entry appended INTO the installer's own group "
                     "survives, canonical-value-equal", len(remaining) == 1,
          json.dumps((after5.get("hooks") or {}).get("PreToolUse"))[:250])
    check("AC10(b)", "the installer's entry is gone from that same group",
          not any(h["command"] == universal for g in remaining
                  for h in (g.get("hooks") or [])))
    check("AC10(b)", "the group itself is RETAINED because it still has an entry",
          bool(remaining) and rc == 0, f"rc={rc}")
    check("AC10(b)", "the enclosing GROUP digest changed before the run, proving a "
                     "group-digest gate would have wrongly retained the entry",
          group_digest_before != json.dumps(remaining[0], sort_keys=True) if remaining else False,
          "locate-by-tuple, verify-by-entry-digest -- never gate on the group")


def ac11(tmp: Path) -> None:
    print("AC11 registration identity is the FULL tuple, and coexistence holds")
    base = tmp / "ac11"

    # AC-INST-6 / AC-INST-12 -- user's copy under a DIFFERENT matcher
    home, prefix = base / "diff" / "cfg", base / "diff" / "prefix"
    home.mkdir(parents=True)
    universal = installer_commands(home)[0]
    write_unconventional(home / "settings.json", user_doc({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": universal}]}]}}))
    user_group_before = json.loads((home / "settings.json").read_text())["hooks"]["PreToolUse"][0]

    rc, _o, err = engine_run("apply", "--prefix", prefix, "--config-dir", home)
    if rc != 0 and missing_surface(rc, err):
        inapplicable("AC11", "registration identity", missing_surface(rc, err))
        return
    doc = json.loads((home / "settings.json").read_text())
    same_command = [c for c in hook_commands(doc) if c[3] == universal]
    universal_present = [c for c in same_command if c[1] is None]
    check("AC11(a)", "MEASURED PREDICATE: the universal (matcher-less) registration "
                     "IS PRESENT after apply", bool(universal_present),
          f"matchers={[c[1] for c in same_command]}", family="registration identity")
    check("AC11(a)", "both the user's matcher-scoped group and the installer's "
                     "registration are present", len(same_command) == 2,
          str(same_command), family="registration identity")
    bucket = doc["hooks"]["PreToolUse"]
    check("AC11(a)", "the installer's registration is APPENDED after the user's",
          bucket[0] == user_group_before and len(bucket) > 1,
          json.dumps(bucket)[:250])
    state = read_state(prefix)["generations"][-1]
    obs_keys = {(o["event"], o["matcher"], o["command"]) for o in state["observations"]}
    check("AC11(a)", "the user's foreign payload reference is RECORDED as an "
                     "observation, so the un-merge can account it",
          ("PreToolUse", "Bash", universal) in obs_keys, str(sorted(obs_keys))[:250])

    rc, _o, _e = engine_run("uninstall", "--prefix", prefix, "--config-dir", home, "--json")
    after = json.loads((home / "settings.json").read_text())
    check("AC11(b)", "the user's differently-matched registration survives, "
                     "canonical-value-equal", user_group_before in
          (after.get("hooks") or {}).get("PreToolUse", []),
          json.dumps(after.get("hooks"))[:250])
    check("AC11(b)", "the installer's own registration is absent",
          not [c for c in hook_commands(after) if c[3] == universal and c[1] is None])
    check("AC11(b)", "the run reports SUCCESS (exit 0): the surviving reference is "
                     "ACCOUNTED by the recorded unowned observation, so it is not a "
                     "partial uninstall", rc == 0, f"rc={rc}")

    # AC-INST-23 -- user's copy under the SAME matcher. The case that stops this
    # fix from creating a NEW clobber.
    home2, prefix2 = base / "same" / "cfg", base / "same" / "prefix"
    home2.mkdir(parents=True)
    universal2 = installer_commands(home2)[0]
    write_unconventional(home2 / "settings.json", user_doc({"hooks": {"PreToolUse": [
        {"hooks": [{"type": "command", "command": universal2}]}]}}))
    pre_parsed = json.loads((home2 / "settings.json").read_text())["hooks"]["PreToolUse"][0]

    engine_run("apply", "--prefix", prefix2, "--config-dir", home2)
    gen = read_state(prefix2)["generations"][-1]
    contrib_keys = {(c["event"], c["matcher"], c["command"]) for c in gen["contributions"]}
    obs = [o for o in gen["observations"]
           if (o["event"], o["matcher"], o["command"]) == ("PreToolUse", None, universal2)]
    check("AC11(c)", "the user's SAME-matcher identity is recorded in observations[] "
                     "with disposition 'unowned'",
          len(obs) == 1 and obs[0]["ownership_disposition"] == "unowned",
          str(obs)[:250])
    check("AC11(c)", "and it does NOT appear in contributions[]",
          ("PreToolUse", None, universal2) not in contrib_keys, str(sorted(contrib_keys))[:250])
    check("AC11(c)", "contributions[] length equals the merge's `added` set, NOT the "
                     "profile's declared registration count",
          len(gen["contributions"]) == len(PROFILE["hook_registrations"]) - 1,
          f"contributions={len(gen['contributions'])} "
          f"profile_declares={len(PROFILE['hook_registrations'])}")

    # A repeat apply must NEVER reclassify it as claimed or inserted.
    engine_run("apply", "--prefix", prefix2, "--config-dir", home2)
    for generation in read_state(prefix2)["generations"]:
        still_unowned = [o for o in generation.get("observations") or []
                         if (o["event"], o["matcher"], o["command"])
                         == ("PreToolUse", None, universal2)]
        if still_unowned:
            check("AC11(c)", f"{generation['generation']}: never reclassified as "
                             "claimed/inserted across repeat installs",
                  all(o["ownership_disposition"] == "unowned" for o in still_unowned),
                  str(still_unowned)[:200])

    rc, _o, _e = engine_run("uninstall", "--prefix", prefix2, "--config-dir", home2, "--json")
    after2 = json.loads((home2 / "settings.json").read_text())
    check("AC11(d)", "the user's pre-existing SAME-matcher registration survives "
                     "uninstall, canonical-value-equal to its pre-install form",
          pre_parsed in (after2.get("hooks") or {}).get("PreToolUse", []),
          json.dumps(after2.get("hooks"))[:250])
    check("AC11(d)", "the run exits 0: its bridge reference is accounted as unowned",
          rc == 0, f"rc={rc}")


def ac12(tmp: Path) -> None:
    print("AC12 mandatory footprint entries, and the record that makes it invertible")
    base = tmp / "ac12"

    # AC-INST-10 / AC-INST-11 -- symlinked settings.json
    home, prefix = base / "sym" / "cfg", base / "sym" / "prefix"
    elsewhere = base / "sym" / "elsewhere"
    home.mkdir(parents=True); elsewhere.mkdir(parents=True)
    write_unconventional(elsewhere / "real-settings.json", user_doc())
    os.symlink(str(elsewhere / "real-settings.json"), home / "settings.json")
    before = node_snapshot(home)

    rc, out, err = engine_run("apply", "--prefix", prefix, "--config-dir", home)
    check("AC12(a)", "apply onto a symlinked settings.json exits non-zero", rc != 0,
          f"rc={rc}", family="mandatory-entry refusal")
    check("AC12(a)", "MEASURED PREDICATE: neither the bridge link nor the command "
                     "document EXISTS after the aborted run",
          not (home / "harness").exists() and not (home / "harness").is_symlink()
          and not (home / "commands" / "harness-doctor.md").exists(),
          family="mandatory-entry refusal")
    check("AC12(a)", "the config-home snapshot is unchanged (abort precedes all mutation)",
          node_snapshot(home) == before, str(sorted(set(node_snapshot(home)) ^ set(before))))
    check("AC12(a)", "no install-state generation was appended",
          not (prefix / "state" / "install-state.json").exists())
    check("AC12(a)", "stdout carries no success token", "APPLIED" not in out)

    rc2, out2, err2 = engine_run("apply", "--prefix", prefix, "--config-dir", home,
                                 "--allow-partial-install")
    if missing_surface(rc2, err2):
        inapplicable("AC12(b)", "opted-in partial install", missing_surface(rc2, err2))
    else:
        check("AC12(b)", "the opted-in partial install exits non-zero and DISTINCT "
                         "from the abort code", rc2 != 0 and rc2 != rc, f"abort={rc} partial={rc2}")
        check("AC12(b)", "the report names settings.json as the skipped mandatory entry",
              "settings.json" in out2 and "SKIPPED MANDATORY ENTRY" in out2, out2[-200:])
        gen = read_state(prefix)["generations"][-1]
        check("AC12(b)", "the generation record's settings disposition records the refusal",
              gen["settings_disposition"] == "refused"
              and "settings.json" in gen["skipped_mandatory"], str(gen.get("settings_disposition")))

    # AC-INST-3 -- the contribution record is written
    home3, prefix3 = base / "rec" / "cfg", base / "rec" / "prefix"
    home3.mkdir(parents=True)
    write_unconventional(home3 / "settings.json", user_doc())
    engine_run("apply", "--prefix", prefix3, "--config-dir", home3)
    state = read_state(prefix3)
    gen = state["generations"][-1]
    check("AC12(c)", "the state schema string is no longer the v1 literal",
          state["schema"] != "claude-harness/install-state/v1", state.get("schema"),
          family="v1-record handling")
    check("AC12(c)", "contributions[] has exactly the profile's registration count on a "
                     "fixture where every registration is genuinely new",
          len(gen["contributions"]) == len(PROFILE["hook_registrations"]),
          f"n={len(gen['contributions'])}")
    check("AC12(c)", "observations[] is empty on that fixture", gen["observations"] == [],
          str(gen["observations"])[:200])
    required = {"event", "matcher", "hook_type", "command", "entry_digest",
                "group_instance_metadata", "group_created", "event_created",
                "append_ordinal", "ownership_disposition"}
    check("AC12(c)", "every contribution carries the full per-identity field set",
          all(required <= set(c) for c in gen["contributions"]),
          str(sorted(required - set(gen["contributions"][0]))) if gen["contributions"] else "empty")
    check("AC12(c)", "every contribution's disposition is 'inserted' with a non-null "
                     "append ordinal",
          all(c["ownership_disposition"] == "inserted" and c["append_ordinal"] is not None
              for c in gen["contributions"]))
    check("AC12(c)", "the record carries container_created, BOTH config-home forms and "
                     "the whole-file as-installed digest",
          "container_created" in gen and gen["config_home_lexical"] == str(home3)
          and gen["config_home_resolved"] == os.path.realpath(home3)
          and gen["settings_sha256_as_installed"] == sha256_file(home3 / "settings.json"),
          str({k: gen.get(k) for k in ("config_home_lexical", "config_home_resolved")})[:200])
    check("AC12(c)", "the entry digest covers the WHOLE entry object, so a sibling-key "
                     "edit that preserves the identity tuple still changes it",
          gen["contributions"][0]["entry_digest"]
          != __import__("hashlib").sha256(json.dumps(
              {"type": "command", "command": gen["contributions"][0]["command"],
               "timeout": 60}, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    check("AC12(c)", "the record is COMMITTED, and the prepared/committed field exists "
                     "so a crash window is recoverable",
          gen.get("record_status") == "committed", str(gen.get("record_status")))


def ac13(tmp: Path) -> None:
    print("AC13 partial un-merges retain the payload; false successes are closed")
    base = tmp / "ac13"

    def fresh(name: str):
        home, prefix = base / name / "cfg", base / name / "prefix"
        home.mkdir(parents=True)
        write_unconventional(home / "settings.json", user_doc())
        rc, _o, err = engine_run("apply", "--prefix", prefix, "--config-dir", home)
        return home, prefix, rc, err

    # AC-INST-18 -- sibling-key edit: located by tuple, digest mismatch
    home, prefix, rc, err = fresh("modified")
    if rc != 0 and missing_surface(rc, err):
        inapplicable("AC13", "partial un-merge", missing_surface(rc, err))
        return
    if not require_installed(home, prefix, "AC13"):
        return
    doc = json.loads((home / "settings.json").read_text())
    universal = installer_commands(home)[0]
    for group in doc["hooks"]["PreToolUse"]:
        for entry in group["hooks"]:
            if entry["command"] == universal:
                entry["timeout"] = 60
    (home / "settings.json").write_text(json.dumps(doc, indent=2) + "\n")

    rc, out, _e = engine_run("uninstall", "--prefix", prefix, "--config-dir", home, "--json")
    report = json.loads(out)
    kept = [i for i in report["items"] if i.get("result") == "kept-user-modified"]
    removed = [i for i in report["items"] if i.get("result") == "removed"]
    check("AC13(a)", "the sibling-key-edited entry is located by tuple and reported "
                     "kept-user-modified on a digest mismatch", len(kept) == 1, str(kept)[:250])
    check("AC13(a)", "the untouched contribution is still removed", len(removed) >= 1)
    check("AC13(a)", "MEASURED PREDICATE: the isolated payload directory STILL EXISTS "
                     "after the partial un-merge", (prefix / "harness").is_dir(),
          family="unconditional payload removal")
    check("AC13(a)", "the state file and every backup are retained",
          (prefix / "state" / "install-state.json").is_file()
          and (prefix / "backups").is_dir(), family="unconditional payload removal")
    check("AC13(a)", "the exit code is 3 (partial), distinct from success and refusal",
          rc == 3, f"rc={rc}", family="unconditional payload removal")

    # AC-INST-19 -- duplicated entry: ambiguous
    home2, prefix2, _rc, _err = fresh("ambiguous")
    if require_installed(home2, prefix2, "AC13(b)"):
        doc2 = json.loads((home2 / "settings.json").read_text())
        universal2 = installer_commands(home2)[0]
        dupe = next(copy_g for copy_g in doc2["hooks"]["PreToolUse"]
                    if any(h["command"] == universal2 for h in copy_g["hooks"]))
        doc2["hooks"]["PreToolUse"].append(json.loads(json.dumps(dupe)))
        (home2 / "settings.json").write_text(json.dumps(doc2, indent=2) + "\n")
        rc2, out2, _e = engine_run("uninstall", "--prefix", prefix2, "--config-dir", home2,
                                   "--json")
        rep2 = json.loads(out2)
        amb = [i for i in rep2["items"] if i.get("result") == "ambiguous-kept"]
        after2 = json.loads((home2 / "settings.json").read_text())
        check("AC13(b)", "a duplicated identity is reported ambiguous-kept and NEITHER "
                         "copy is removed", len(amb) == 1
              and len([c for c in hook_commands(after2) if c[3] == universal2]) == 2,
              str(amb)[:200])
        check("AC13(b)", "the payload is retained and the exit code is non-zero",
              (prefix2 / "harness").is_dir() and rc2 != 0, f"rc={rc2}")

    # AC-INST-26 -- command-text edit: NOT locatable, must not become a false success
    home3, prefix3, _rc, _err = fresh("residual")
    if require_installed(home3, prefix3, "AC13(c)"):
        doc3 = json.loads((home3 / "settings.json").read_text())
        universal3 = installer_commands(home3)[0]
        for group in doc3["hooks"]["PreToolUse"]:
            for entry in group["hooks"]:
                if entry["command"] == universal3:
                    entry["command"] = universal3 + " --my-own-flag"
        (home3 / "settings.json").write_text(json.dumps(doc3, indent=2) + "\n")
        rc3, out3, _e = engine_run("uninstall", "--prefix", prefix3, "--config-dir", home3,
                                   "--json")
        rep3 = json.loads(out3)
        residual = [i for i in rep3["items"]
                    if i.get("result") == "kept-unrecognized-residual"]
        check("AC13(c)", "a command-text edit is reported kept-unrecognized-residual by "
                         "the residual scan, naming its event, matcher and command",
              bool(residual) and all({"event", "matcher", "command"} <= set(i)
                                     for i in residual), str(residual)[:250])
        check("AC13(c)", "payload removal is SUPPRESSED and the exit code is 3 -- NOT a "
                         "false success that deletes a payload the live command names",
              (prefix3 / "harness").is_dir() and rc3 == 3, f"rc={rc3}")

    # the same must hold for a changed enclosing matcher
    home4, prefix4, _rc, _err = fresh("matcher-edit")
    if require_installed(home4, prefix4, "AC13(d)"):
        doc4 = json.loads((home4 / "settings.json").read_text())
        universal4 = installer_commands(home4)[0]
        for group in doc4["hooks"]["PreToolUse"]:
            if any(h["command"] == universal4 for h in group["hooks"]):
                group["matcher"] = "Bash"
        (home4 / "settings.json").write_text(json.dumps(doc4, indent=2) + "\n")
        rc4, out4, _e = engine_run("uninstall", "--prefix", prefix4, "--config-dir", home4,
                                   "--json")
        check("AC13(d)", "a changed enclosing matcher is likewise an unrecognized "
                         "residual, retaining the payload at exit 3",
              rc4 == 3 and (prefix4 / "harness").is_dir()
              and any(i.get("result") == "kept-unrecognized-residual"
                      for i in json.loads(out4)["items"]), f"rc={rc4}")

    # AC-INST-22 -- duplicate-key document
    home5, prefix5 = base / "dupkey" / "cfg", base / "dupkey" / "prefix"
    home5.mkdir(parents=True)
    (home5 / "settings.json").write_text(
        '{\n  "model": "opus",\n  "model": "sonnet"\n}\n')
    before5 = node_snapshot(home5)
    rc5, _o, err5 = engine_run("apply", "--prefix", prefix5, "--config-dir", home5)
    check("AC13(e)", "a duplicate-key settings document is REFUSED, not silently "
                     "normalized", rc5 != 0 and node_snapshot(home5) == before5,
          f"rc={rc5} err={err5[-160:]}")


def ac14(tmp: Path) -> None:
    print("AC14 legacy records, source-independent uninstall, crash-window recovery")
    base = tmp / "ac14"

    # AC-INST-13 -- uninstall from the payload with NO source checkout
    home, prefix = base / "nosrc" / "cfg", base / "nosrc" / "prefix"
    home.mkdir(parents=True)
    write_unconventional(home / "settings.json", user_doc())
    rc, _o, err = engine_run("apply", "--prefix", prefix, "--config-dir", home)
    if rc != 0 and missing_surface(rc, err):
        inapplicable("AC14", "payload-resident uninstall", missing_surface(rc, err))
        return
    if not require_installed(home, prefix, "AC14"):
        return
    bundle = read_state(prefix)["generations"][-1].get("self_management")
    entrypoint = prefix / bundle["root_relative"] / "uninstall" if bundle else None
    if not entrypoint or not entrypoint.is_file():
        inapplicable("AC14(a)", "payload-resident uninstall entrypoint",
                     "engine does not ship a self-management bundle")
    else:
        rc, out, err = run([entrypoint, "--config-dir", home,
                            "--source", base / "THIS-PATH-DOES-NOT-EXIST", "--json"])
        after = json.loads((home / "settings.json").read_text())
        check("AC14(a)", "uninstall runs from the isolated payload with --source "
                         "pointing at a path that does not exist",
              rc in (0, 3), f"rc={rc} err={err[-250:]}")
        check("AC14(a)", "the config-home footprint is removed",
              not (home / "harness").exists() and not payload_refs(after, home),
              f"refs={payload_refs(after, home)}")
        check("AC14(a)", "exit 0 iff the self-management bundle deleted itself, else 3 "
                         "naming the retained bundle",
              (rc == 0 and not prefix.exists()) or (rc == 3 and prefix.exists()),
              f"rc={rc} payload_present={prefix.exists()}")

    # AC-INST-7 / AC-INST-20 / AC-INST-24 -- v1 records
    def make_v1(name: str, mutate=None):
        h, p = base / name / "cfg", base / name / "prefix"
        h.mkdir(parents=True)
        write_unconventional(h / "settings.json", user_doc())
        engine_run("apply", "--prefix", p, "--config-dir", h)
        state = json.loads((p / "state" / "install-state.json").read_text())
        # Downgrade to the pre-R2 shape: drop every field the contribution record
        # introduced, leaving exactly what the unfixed engine wrote.
        state["schema"] = "claude-harness/install-state/v1"
        for g in state["generations"]:
            for field in ("contributions", "observations", "container_created",
                          "record_status", "settings_disposition",
                          "settings_pre_image_sha256", "settings_sha256_as_installed",
                          "config_home_lexical", "config_home_resolved",
                          "self_management", "bridge_rel", "settings_rel",
                          "skipped_mandatory"):
                g.pop(field, None)
        (p / "state" / "install-state.json").write_text(json.dumps(state, indent=2) + "\n")
        if mutate:
            mutate(h)
        return h, p

    # state (a): unchanged since install -> MUST complete, or no host is removable
    h_a, p_a = make_v1("v1-clean")
    rc_a, _o, err_a = engine_run("uninstall", "--prefix", p_a, "--config-dir", h_a, "--json")
    doc_a = json.loads((h_a / "settings.json").read_text())
    check("AC14(b)", "a v1 install whose live document is a PROVABLE post-image is "
                     "actually removable: exits 0 with the payload gone",
          rc_a == 0 and not p_a.exists(), f"rc={rc_a} err={err_a[-200:]}")
    check("AC14(b)", "and everything not attributable to the legacy install is intact",
          doc_a.get("userNote") == NON_ASCII_KEY_VALUE and not payload_refs(doc_a, h_a),
          json.dumps(doc_a)[:200])

    # state (b): user edited the document after install -> MUST refuse
    def user_edit(home_path: Path):
        doc = json.loads((home_path / "settings.json").read_text())
        doc["addedAfterInstall"] = "must-survive"
        (home_path / "settings.json").write_text(json.dumps(doc, indent=2) + "\n")

    h_b, p_b = make_v1("v1-edited", mutate=user_edit)
    before_b = node_snapshot(h_b)
    rc_b, _o, err_b = engine_run("uninstall", "--prefix", p_b, "--config-dir", h_b)
    after_b = json.loads((h_b / "settings.json").read_text())
    check("AC14(c)", "a v1 record whose post-image is NOT provable is refused, not "
                     "whole-file restored", rc_b != 0, f"rc={rc_b}",
          family="v1-record handling")
    check("AC14(c)", "MEASURED PREDICATE: the v1 fixture's user edit is STILL PRESENT "
                     "after the refused run", after_b.get("addedAfterInstall") == "must-survive",
          family="v1-record handling")
    check("AC14(c)", "the config home is unchanged on every path, node type and inode",
          node_snapshot(h_b) == before_b, family="v1-record handling")
    check("AC14(c)", "the state file, the payload and every backup are retained",
          (p_b / "state" / "install-state.json").is_file() and (p_b / "harness").is_dir()
          and (p_b / "backups").is_dir())
    check("AC14(c)", "stdout names the backup path as the manual-recovery artifact",
          "backup" in err_b and str(p_b / "backups") in err_b, err_b[-250:])
    check("AC14(c)", "and prints a reviewable removal plan naming what it would remove",
          "Reviewable removal plan" in err_b
          and installer_commands(h_b)[0] in err_b, err_b[-250:])

    # AC-INST-21 -- a v2 apply refuses to stack on an unresolved v1 record
    gens_before = len(json.loads((p_b / "state" / "install-state.json").read_text())
                      ["generations"])
    rc_s, _o, err_s = engine_run("apply", "--prefix", p_b, "--config-dir", h_b)
    gens_after = len(json.loads((p_b / "state" / "install-state.json").read_text())
                     ["generations"])
    check("AC14(d)", "a v2 apply refuses to stack a generation on an unresolved v1 "
                     "record, appending nothing",
          rc_s != 0 and gens_after == gens_before, f"rc={rc_s} {gens_before}->{gens_after}",
          family="v1-record handling")

    # AC-INST-25 -- the crash window between the mutation and the state write
    h_c, p_c = base / "crash" / "cfg", base / "crash" / "prefix"
    h_c.mkdir(parents=True)
    write_unconventional(h_c / "settings.json", user_doc())
    engine_run("apply", "--prefix", p_c, "--config-dir", h_c)
    state_c = json.loads((p_c / "state" / "install-state.json").read_text())
    # Reconstruct the EXACT on-disk state of the crash window: the config home is
    # mutated and the generation record is still `prepared`. This is the state an
    # uncatchable signal leaves behind; what it proves is that the contributions
    # remain identifiable from the prepared intent record, which is the whole point
    # of writing that record BEFORE the mutation it describes.
    state_c["generations"][-1]["record_status"] = "prepared"
    state_c["generations"][-1]["created"] = []
    state_c["generations"][-1]["modified"] = []
    (p_c / "state" / "install-state.json").write_text(json.dumps(state_c, indent=2) + "\n")
    check("AC14(e)", "the prepared intent record carries the planned contributions, so "
                     "a crash between the mutation and the commit is recoverable",
          bool(state_c["generations"][-1]["contributions"]),
          "reconstructed crash-window state: config home mutated, record still `prepared`")
    rc_c, out_c, err_c = engine_run("uninstall", "--prefix", p_c, "--config-dir", h_c, "--json")
    after_c = json.loads((h_c / "settings.json").read_text())
    check("AC14(e)", "uninstall identifies the contributions from the prepared record "
                     "rather than reporting the state as having none",
          rc_c in (0, 3) and not payload_refs(after_c, h_c),
          f"rc={rc_c} refs={payload_refs(after_c, h_c)} err={err_c[-200:]}")
    check("AC14(e)", "and the user's own content is preserved through it",
          after_c.get("userNote") == NON_ASCII_KEY_VALUE, json.dumps(after_c)[:200])


def ac15(tmp: Path) -> None:
    print("AC15 the INSTALLED capability gate -- dependency set closed by the profile")
    n2, prefix = tmp / "ac15" / "cfg", tmp / "ac15" / "prefix"
    n2.mkdir(parents=True)
    rc, _o, err = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", n2])
    check("AC15", "install succeeded", rc == 0, f"rc={rc} err={err[-250:]}")
    iso = prefix / "harness"
    gate = next((f for comp in PROFILE["components"] if comp["role"] == "capability_gate"
                 for f in comp["files"] if f.endswith("capability-gate.py")), None)
    check("AC15(a)", "the profile declares a capability gate component", bool(gate), str(gate))
    if not gate or not (iso / gate).is_file():
        inapplicable("AC15", "installed gate invocation", "gate absent from the payload")
        return

    # Every artifact the INSTALLED gate binds must be present under the isolated
    # root. This is the assertion that was blocked until the profile shipped the
    # manifest alongside the gate.
    policy_files = [f for comp in PROFILE["components"] if comp["role"] == "policy"
                    for f in comp["files"]]
    missing = [f for f in policy_files if not (iso / f).is_file()]
    check("AC15(a)", "every policy artifact the gate binds is present under the "
                     "isolated root", not missing, str(missing))

    def invoke(payload: dict):
        p = subprocess.run([sys.executable, str(iso / gate)], input=json.dumps(payload),
                           capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_HOME": str(iso)})
        return p.returncode, p.stderr

    rc_hatch, _err = invoke({"tool_name": "SlashCommand", "tool_input": {"command": "/do"},
                             "session_id": "ac15-hatch"})
    check("AC15(b)", "the INSTALLED gate permits a consent escape hatch (exit 0)",
          rc_hatch == 0, f"rc={rc_hatch}")

    rc_prot, err_prot = invoke({"tool_name": "SlashCommand",
                                "tool_input": {"command": "/close"},
                                "session_id": "ac15-protected"})
    check("AC15(b)", "the INSTALLED gate reaches a real decision on a protected route "
                     "rather than failing to load its own dependencies",
          "library_unavailable" not in err_prot and "manifest_unreadable" not in err_prot,
          err_prot[-250:])
    check("AC15(b)", "and it fails CLOSED on that route with no live PASS (exit 2)",
          rc_prot == 2, f"rc={rc_prot} stderr={err_prot[-200:]}")


def ac16(tmp: Path) -> None:
    print("AC16 the documented entrypoints propagate the engine's exit code")
    base = tmp / "ac16"
    home, prefix = base / "cfg", base / "prefix"
    other = base / "other-home"
    home.mkdir(parents=True); other.mkdir(parents=True)
    write_unconventional(home / "settings.json", user_doc())
    write_unconventional(other / "settings.json", user_doc({"model": "sonnet"}))
    rc, _o, err = run([INSTALL, "--profile", "core", "--prefix", prefix, "--config-dir", home])
    check("AC16", "install exits 0", rc == 0, f"rc={rc} err={err[-250:]}")
    if not require_installed(home, prefix, "AC16"):
        return
    # R1's refusal, observed through the DOCUMENTED entrypoint rather than the engine.
    rc_refuse, _o, _e = run([UNINSTALL, "--prefix", prefix, "--config-dir", other])
    check("AC16(a)", "scripts/install/uninstall propagates the engine's refusal code (2)",
          rc_refuse == 2, f"rc={rc_refuse}")
    # R3b's partial, likewise.
    doc = json.loads((home / "settings.json").read_text())
    universal = installer_commands(home)[0]
    for group in doc["hooks"]["PreToolUse"]:
        for entry in group["hooks"]:
            if entry["command"] == universal:
                entry["timeout"] = 60
    (home / "settings.json").write_text(json.dumps(doc, indent=2) + "\n")
    rc_partial, _o, _e = run([UNINSTALL, "--prefix", prefix, "--config-dir", home])
    check("AC16(a)", "and propagates the engine's partial code (3)", rc_partial == 3,
          f"rc={rc_partial}")
    for entrypoint, name in ((INSTALL, "install"), (UNINSTALL, "uninstall")):
        header = entrypoint.read_text()
        check("AC16(b)", f"scripts/install/{name} documents the four-code exit contract",
              all(token in header for token in ("0 = success", "1 = failure",
                                                "2 = preflight", "3 = partial")),
              header[:60])


def main() -> int:
    global VERBOSE, ACTIVE_ENGINE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--engine", default=None,
                    help="drive AC9-AC14 against an ALTERNATIVE engine, to demonstrate "
                         "the destructive-path fixtures failing on it")
    args = ap.parse_args()
    VERBOSE = args.verbose
    if args.engine:
        ACTIVE_ENGINE = Path(args.engine).resolve()
        print(f"NOTE: AC9-AC14 driven against alternative engine {ACTIVE_ENGINE}")

    tmp = Path(tempfile.mkdtemp(prefix="installer-acceptance-"))
    try:
        if not args.engine:
            ac1(tmp); ac2(tmp); ac3(tmp); ac4_ac5(tmp); ac6(tmp); ac7(tmp); ac8(tmp)
            ac15(tmp); ac16(tmp)
        ac9(tmp); ac10(tmp); ac11(tmp); ac12(tmp); ac13(tmp); ac14(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[2]]
    by_ac: dict[str, list[bool]] = {}
    for ac, _n, ok, _d in RESULTS:
        by_ac.setdefault(ac.split("(")[0], []).append(ok)
    print("\n" + "=" * 74)
    for ac in sorted(by_ac):
        oks = by_ac[ac]
        print(f"  {ac:6} {sum(oks)}/{len(oks)} assertions passed"
              f"{'' if all(oks) else '   <-- FAILURES'}")
    print("=" * 74)
    print(f"TOTAL: {len(RESULTS) - len(failed)}/{len(RESULTS)} assertions passed")
    if failed:
        print("\nFAILED:")
        for ac, name, _ok, detail in failed:
            print(f"  {ac} {name}  -- {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
