"""The scratch entries of settings.json reach the scratch roots and nothing else under /tmp (OB-L09).

Root cause. A Read/Edit path rule with ONE leading slash is not absolute: "`/path` = relative to the
settings source", "The single leading slash anchors at the settings source, not the filesystem root. Use
`//Users/alice/file` for absolute paths", and in user settings "A deny rule such as `Read(/secrets/**)` in
user settings blocks `~/.claude/secrets/**`" (code.claude.com/docs/en/permissions.md, "How path patterns
match"). The harness ships as the user settings, so the old `Read(/tmp/**)` covered `~/.claude/tmp/**` and
never /tmp: every read and write of scratch outside the working directory prompted.

The fix names the two scratch roots the harness itself defines, absolute (`//`), for Read and for Edit
("`Edit` rules apply to all built-in tools that edit files", same page):

* the session scratch root, env.TMPDIR = env.CLAUDE_CODE_TMPDIR = /var/tmp/claude-scratch. The CLI puts its
  own session scratchpad under CLAUDE_CODE_TMPDIR (`<root>/claude-<uid>/<project>/<session>/scratchpad`),
  hooks/session-scratch-init.sh registers `<root>/<sid>/`, and mktemp lands in `<root>/`;
* the role scratch root, /tmp/claude-scratch: policies/tool-policy.v1.json grants each role
  `*/tmp/claude-scratch/<role>/` and the agent texts write there (agents/changelog-analyst.md).

Neither root holds harness state: the state root is hooks/lib/harness_state_dir.py's (CLAUDE_STATE_DIR,
default /tmp), whose files (consent flags, the tool streak, /do task and reservation files, grants,
sentinels, agentic-commit/) sit directly in it, never under `claude-scratch/`. STATE_PATHS below enumerates
them (from the sources, plus the names the audit lists) and every one stays uncovered.

The decision model (`decide`) is the CLI's path check as measured on Claude Code 2.1.326, run headless with
a throwaway HOME and a local Messages-API stand-in, the shipped `permissions` block as user settings
(MEASURED below records each case's result line on the base and after the change). In order: a Read/Edit
deny rule refuses; a path inside the working directory goes on to the tool's own rules; outside it, a
matching Read rule (op read) or Edit rule (op write) allows; otherwise the call asks. For Bash, the paths a
recognised file command (cat, ls, rm) names and the targets of `>` redirections go through this check
BEFORE the Bash allow rules, and an outside-the-working-directory ask is not one a Bash allow rule can
lift: `cat > /tmp/claude-tool-streak-abc.json` asks although `Bash(cat:*)` and
`Bash(cat > /tmp/*.json:*)` both match its text. That is why the `Bash(cat > /tmp/*...)` and
`Bash(rm -f /tmp/*...)` entries are not this lane's: they never granted a /tmp write, and they are
subsumed by `Bash(cat:*)` and `Bash(rm:*)`.
"""
from __future__ import annotations

import json
import posixpath
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
PERMS = SETTINGS["permissions"]
ENV = SETTINGS["env"]

sys.path.insert(0, str(REPO / "hooks" / "lib"))
from harness_state_dir import _DEFAULT_ROOT as STATE_DEFAULT_ROOT  # noqa: E402

SESSION_ROOT = "/var/tmp/claude-scratch"
ROLE_ROOT = "/tmp/claude-scratch"
SCRATCH_ROOTS = (SESSION_ROOT, ROLE_ROOT)
# A session scratchpad as the CLI lays it out under CLAUDE_CODE_TMPDIR, and a harness per-session dir.
SESSION_SCRATCH = f"{SESSION_ROOT}/claude-0/-home-u-proj/0b0e6c1e-0000-4000-8000-000000000000/scratchpad"
HARNESS_SESSION_DIR = f"{SESSION_ROOT}/0b0e6c1e-0000-4000-8000-000000000000"
WORKDIR = "/home/u/proj"
SETTINGS_SOURCE = "<home>/.claude"  # user settings: a single leading slash anchors here


# ------------------------------------------------------------------ the CLI's path-rule match
def _specifiers(tool: str, kind: str) -> list[str]:
    pre = tool + "("
    return [e[len(pre):-1] for e in PERMS.get(kind, []) if e.startswith(pre) and e.endswith(")")]


def anchored(spec: str) -> str | None:
    """The absolute pattern a path specifier names, or None for one that never reaches the filesystem
    root: `//p` is absolute, `/p` anchors at the settings source, `~/p` at home; a bare name matches at any
    depth (gitignore), which we return as `**/name`."""
    if spec.startswith("//"):
        return spec[1:]
    if spec.startswith("/"):
        return SETTINGS_SOURCE + spec
    if spec.startswith("~/"):
        return "<home>/" + spec[2:]
    if spec.startswith("./"):
        return WORKDIR + "/" + spec[2:]
    if "/" not in spec.rstrip("/"):
        return "**/" + spec
    return WORKDIR + "/" + spec


def _glob_rx(pattern: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out)


def matches(spec: str, path: str) -> bool:
    pat = anchored(spec)
    if pat is None:
        return False
    if pat.startswith("**/"):
        return re.fullmatch(_glob_rx(pat[3:]), posixpath.basename(path)) is not None or \
            re.fullmatch(_glob_rx(pat), path.lstrip("/")) is not None
    return re.fullmatch(_glob_rx(pat), path) is not None


def decide(op: str, path: str, builtin: bool = False) -> str:
    """allow / ask / deny for a Bash file operand or redirect target, or (builtin=True) for the Read or
    Write tool itself, which a bare tool-wide entry (`Read`) also allows: measured, the bare `Read` lets
    the Read tool read outside the working directory while `cat` of the same file asks."""
    path = posixpath.normpath(path)
    tools = ("Read",) if op == "read" else ("Edit",)
    for tool in ("Read", "Edit") if op != "read" else ("Read",):
        if any(matches(s, path) for s in _specifiers(tool, "deny")):
            return "deny"
    for tool in tools:
        if any(matches(s, path) for s in _specifiers(tool, "ask")):
            return "ask"
    if path == WORKDIR or path.startswith(WORKDIR + "/"):
        return "allow" if op == "read" else "ask-or-mode"
    for tool in tools:
        if any(matches(s, path) for s in _specifiers(tool, "allow")):
            return "allow"
        if builtin and tool in PERMS.get("allow", []):
            return "allow"
    return "ask"


# ------------------------------------------------------------------ the harness's own scratch names
def test_session_root_is_the_pinned_tmpdir():
    """The session root is what settings.json pins for both the harness (TMPDIR) and the CLI."""
    assert ENV["TMPDIR"] == ENV["CLAUDE_CODE_TMPDIR"] == SESSION_ROOT
    for hook in ("session-scratch-init.sh", "sessionend-scratch-sweep.sh"):
        assert 'ROOT="${TMPDIR:-/var/tmp/claude-scratch}"' in (REPO / "hooks" / hook).read_text()


def test_role_root_is_the_policy_role_scratch():
    policy = json.loads((REPO / "policies" / "tool-policy.v1.json").read_text())
    prefixes = {p for role in policy["roles"].values() for p in role.get("allowed_write_path_prefixes", [])
                if "claude-scratch" in p}
    assert prefixes, "no role scratch prefix found"
    assert all(re.fullmatch(r"\*/tmp/claude-scratch/[a-z-]+/", p) for p in prefixes), prefixes


@pytest.mark.parametrize("root", SCRATCH_ROOTS)
@pytest.mark.parametrize("tool", ["Read", "Edit"])
def test_exact_scratch_entry_present(tool, root):
    assert f"{tool}(/{root}/**)" in PERMS["allow"]


def test_no_single_slash_path_rule():
    """No Read/Edit rule spelled with one leading slash: it would anchor at the settings source."""
    bad = [e for kind in ("allow", "deny", "ask") for t in ("Read", "Edit")
           for e in (f"{t}({s})" for s in _specifiers(t, kind)) if re.match(r"/[^/]", e[len(t) + 1:])]
    assert bad == []


def test_old_entry_never_reached_tmp():
    """The base entry, modelled: `Read(/tmp/**)` names <home>/.claude/tmp/**, not /tmp."""
    assert anchored("/tmp/**") == "<home>/.claude/tmp/**"
    assert not matches("/tmp/**", f"{ROLE_ROOT}/qa/out.txt")
    assert "Read(/tmp/**)" not in PERMS["allow"]


def test_no_tmp_wide_grant():
    """Never /tmp (or /var/tmp) as a whole: no additionalDirectories under them, no wider path rule."""
    dirs = PERMS.get("additionalDirectories", [])
    assert not [d for d in dirs if posixpath.normpath(d) in ("/tmp", "/var/tmp", "/var", "/")
                or posixpath.normpath(d).startswith(("/tmp/", "/var/tmp/"))]
    for tool in ("Read", "Edit"):
        for spec in _specifiers(tool, "allow"):
            pat = anchored(spec)
            if pat and pat.startswith(("/tmp", "/var/tmp")):
                assert pat in (f"{SESSION_ROOT}/**", f"{ROLE_ROOT}/**"), spec
    assert "Edit(//tmp/**)" not in PERMS["allow"] and "Read(//tmp/**)" not in PERMS["allow"]


def test_state_root_is_not_a_scratch_root():
    state_root = ENV.get("CLAUDE_STATE_DIR") or STATE_DEFAULT_ROOT
    for root in SCRATCH_ROOTS:
        assert not (state_root + "/").startswith(root + "/"), (state_root, root)


# ------------------------------------------------------------------ must pass
MUST_PASS = [
    ("cat <session scratch>/notes.md", "read", f"{SESSION_SCRATCH}/notes.md"),
    ("echo done > <session scratch>/report.md", "write", f"{SESSION_SCRATCH}/report.md"),
    ("ls <session scratch>", "read", SESSION_SCRATCH),
    ("Read tool <session scratch>/notes.md", "read", f"{SESSION_SCRATCH}/notes.md"),
    ("Write tool <session scratch>/w.md", "write", f"{SESSION_SCRATCH}/w.md"),
    ("mktemp under TMPDIR", "write", f"{SESSION_ROOT}/tmp.AbC123"),
    ("harness per-session dir", "write", f"{HARNESS_SESSION_DIR}/out.txt"),
    ("echo done > role scratch", "write", f"{ROLE_ROOT}/qa/out.txt"),
    ("Write tool role scratch commit message", "write", f"{ROLE_ROOT}/changelog-analyst/commit-msg-1.txt"),
]


@pytest.mark.parametrize("label,op,path", MUST_PASS, ids=[c[0] for c in MUST_PASS])
def test_scratch_passes(label, op, path):
    assert decide(op, path, " tool " in label) == "allow", label


# ------------------------------------------------------------------ must still prompt or refuse
_NAME_SOURCES = [
    re.compile(r"harness_state_dir\(\)\}?/([A-Za-z0-9_.{}*\-/\[\]]+)"),
    re.compile(r"harness_state_dir\(\)\s*\+\s*['\"]/([^'\"]+)['\"]"),
    re.compile(r"(?:join|Path)\(\s*harness_state_dir\(\)\s*,\s*[fr]?['\"]([^'\"]+)['\"]"),
    re.compile(r"\$\(harness_state_dir\)/([A-Za-z0-9_.{}*\-/$]+)"),
    re.compile(r"(?<![\w./-])/tmp/((?:claude-|agentic-commit|codex-)[A-Za-z0-9_.{}*\-/$]*)"),
]
# Named by the audit (AUDIT G2/OB-L09) and the hooks' comments, beside what the scan finds.
LISTED_STATE_NAMES = [
    "claude-orchestrator-consent-{sid}.flag",
    "claude-tool-streak-{sid}.json",
    "claude-do-task-{sid}.json",
    "claude-do-resv-{ts}",
    "claude-commit-grant-{a}-{b}.json",
    "claude-push-grant-{sid}-{n}.json",
    "claude-bulk-commit-sentinel-{x}.json",
    "claude-grants/{task}.json",
    "claude-git-residual-override",
    "claude-dev-userintent-{sid}.flag",
    "claude-capability-0/state.json",
    "agentic-commit/push/{h}/{b}/main.json",
    "agentic-commit/push-analyst/{h}/main-chainB.validated.sentinel.json",
    "agentic-commit/merge-analyst/audit/{x}.log",
    "agentic-commit/locks/{x}.lock",
]


def _scanned_state_names() -> set[str]:
    names: set[str] = set()
    files = [*REPO.glob("hooks/**/*.py"), *REPO.glob("hooks/**/*.sh"),
             *REPO.glob("scripts/**/*.py"), *REPO.glob("scripts/**/*.sh")]
    for f in files:
        if "/tests/" in f.as_posix():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for rx in _NAME_SOURCES:
            names.update(m.group(1) for m in rx.finditer(text))
    return names


def _instantiate(name: str) -> str:
    name = re.sub(r"\$\{[^}]*\}|\$[A-Za-z_]+|\{[^}]*\}?|\[[^\]]*\]", "abc", name)
    name = name.replace("**", "abc").replace("*", "abc").rstrip("/")
    return name or "abc"


def state_paths() -> list[str]:
    roots = {STATE_DEFAULT_ROOT, ENV.get("CLAUDE_STATE_DIR") or STATE_DEFAULT_ROOT}
    names = sorted(_scanned_state_names() | set(LISTED_STATE_NAMES))
    return sorted({posixpath.normpath(f"{root}/{_instantiate(n)}") for root in roots for n in names})


def test_state_scan_is_not_vacuous():
    scanned = _scanned_state_names()
    assert "claude-orchestrator-consent-{sid}.flag" in scanned
    assert "claude-tool-streak-{session_id}.json" in scanned
    assert not [n for n in scanned if n.split("/")[0] == "claude-scratch"], "state under a scratch root"
    assert len(state_paths()) >= 20


@pytest.mark.parametrize("path", state_paths())
def test_state_file_not_covered(path):
    """No path rule covers a harness state file: an Edit, Write or redirect to it still asks."""
    for tool in ("Read", "Edit"):
        hit = [s for s in _specifiers(tool, "allow") if matches(s, path)]
        assert hit == [], (tool, hit)
    assert decide("write", path) == "ask"
    assert decide("write", path, builtin=True) == "ask"


MUST_STILL_ASK = [
    ("echo true > /tmp/claude-orchestrator-consent-abc.flag", "write", "/tmp/claude-orchestrator-consent-abc.flag"),
    ("echo '{}' > /tmp/claude-tool-streak-abc.json", "write", "/tmp/claude-tool-streak-abc.json"),
    ("cat > /tmp/claude-tool-streak-abc.json <<EOF", "write", "/tmp/claude-tool-streak-abc.json"),
    ("rm -f /tmp/claude-do-task-abc.json", "write", "/tmp/claude-do-task-abc.json"),
    ("Write tool consent flag", "write", "/tmp/claude-orchestrator-consent-abc.flag"),
    ("Write tool agentic-commit grant", "write", "/tmp/agentic-commit/push/x/y/main.json"),
    ("echo done > /tmp/probe-report.md", "write", "/tmp/probe-report.md"),
    ("traversal out of the scratch root", "write",
     f"{SESSION_SCRATCH}/../../../../../../../tmp/claude-orchestrator-consent-abc.flag"),
    ("sibling name of the role root", "write", "/tmp/claude-scratch-userintent-abc.flag"),
    ("sibling name of the session root", "write", "/var/tmp/claude-scratchy/x"),
    ("the /var/tmp graphify cache", "write", "/var/tmp/claude-graphify/x"),
    ("the CLI's own /tmp tree", "write", "/tmp/claude-0/x/tasks/y.output"),
]


@pytest.mark.parametrize("label,op,path", MUST_STILL_ASK, ids=[c[0] for c in MUST_STILL_ASK])
def test_state_and_raw_tmp_still_ask(label, op, path):
    assert decide(op, path, " tool " in label) == "ask", label


def test_scratch_root_itself_not_writable():
    """`<root>/**` covers what is inside each root, not a file named like it beside it."""
    for root in SCRATCH_ROOTS:
        assert decide("write", root + ".flag") == "ask"
        assert decide("write", root + "/x") == "allow"


# ------------------------------------------------------------------ what the CLI did (2.1.326)
# Each case driven once through the installed CLI, headless, default permission mode, the settings
# file's `permissions` block as the throwaway HOME's user settings; the first line of the tool result.
MEASURED = {
    "cat <session scratch>/notes.md": ("blocked: outside the allowed working directories", "ran"),
    "echo done > <session scratch>/report.md": ("Output redirection ... needs approval", "ran"),
    "ls <session scratch>": ("blocked: outside the allowed working directories", "ran"),
    "Read tool <session scratch>/notes.md": ("ran (the bare `Read` entry)", "ran"),
    "Write tool <session scratch>/w.md": ("haven't granted it yet", "ran"),
    "echo done > role scratch": ("Output redirection ... needs approval", "ran"),
    "Write tool role scratch": ("haven't granted it yet", "ran"),
    "echo true > /tmp/claude-orchestrator-consent-abc.flag": ("needs approval", "needs approval"),
    "echo '{}' > /tmp/claude-tool-streak-abc.json": ("needs approval", "needs approval"),
    "cat > /tmp/claude-tool-streak-abc.json <<EOF": ("needs approval", "needs approval"),
    "rm -f /tmp/claude-do-task-abc.json": ("needs approval", "needs approval"),
    "Write tool consent flag": ("haven't granted it yet", "haven't granted it yet"),
    "Write tool agentic-commit grant": ("haven't granted it yet", "haven't granted it yet"),
    "echo done > /tmp/probe-report.md": ("needs approval", "needs approval"),
    "traversal out of the scratch root": ("needs approval", "needs approval"),
}


def test_model_agrees_with_measurement():
    """The model gives, for the settings as they stand, the decision the CLI gave after the change."""
    labels = {c[0]: c for c in MUST_PASS + MUST_STILL_ASK}
    labels["Write tool role scratch"] = labels["Write tool role scratch commit message"]
    for label, (_base, after) in MEASURED.items():
        case = labels[label]
        want = "allow" if after.startswith("ran") else "ask"
        assert decide(case[1], case[2], " tool " in label) == want, label
