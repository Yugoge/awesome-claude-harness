"""The scratch entries of settings.json reach the scratch the agent needs and no gate-read file (OB-L09).

Root cause. A Read/Edit path rule with ONE leading slash is not absolute: "`/path` = relative to the
settings source", "The single leading slash anchors at the settings source, not the filesystem root. Use
`//Users/alice/file` for absolute paths", and in user settings "A deny rule such as `Read(/secrets/**)` in
user settings blocks `~/.claude/secrets/**`" (code.claude.com/docs/en/permissions.md, "How path patterns
match"). The harness ships as the user settings, so the old `Read(/tmp/**)` covered `~/.claude/tmp/**` and
never /tmp: every read and write of scratch outside the working directory prompted.

The fix names, absolute (`//`), for Read and for Edit ("`Edit` rules apply to all built-in tools that edit
files", same page), exactly the scratch an agent writes, and nothing a hook reads to decide:

* the CLI's own session scratchpad, `<TMPDIR>/claude-<uid>/<project>/<session>/scratchpad` (the CLI lays it
  out under CLAUDE_CODE_TMPDIR, which settings.json pins equal to TMPDIR): the pattern
  `<TMPDIR>/claude-[0-9]*/*/*/scratchpad` and everything under it. NOT the TMPDIR root as a whole: it also
  holds gate-read files (GATE_READ below: the daemon-restart grant flag and its lock that
  hooks/pretool-bash-safety.sh consumes, the git blessed-token grants hooks/git-keystone/reference-transaction
  checks, each session dir's `.owner` that hooks/sessionend-scratch-sweep.sh and hooks/lib/scratch_owner.py
  trust, doc-sync's dedupe state, the CLI's task outputs);
* the role scratch root, /tmp/claude-scratch: policies/tool-policy.v1.json grants each role
  `*/tmp/claude-scratch/<role>/` and the agent texts write there (agents/changelog-analyst.md). No hook
  builds a path under it (SOURCE_SCAN checks).

The hook state root (hooks/lib/harness_state_dir.py, CLAUDE_STATE_DIR, default /tmp) keeps its files
directly in it; STATE_PATHS enumerates them and they stay uncovered too. Every must-ask path is checked
for the shipped settings and for the shipped settings plus settings.machine.example.json's overlay, which
moves TMPDIR to /opt/demo/scratch and appends its own pair.

The decision model (`decide`) is the CLI's path check as measured on Claude Code 2.1.326, run headless with
a throwaway HOME and a local Messages-API stand-in, the `permissions` block as user settings (MEASURED
records the base, the first commit of this lane and the fix). In order: a Read/Edit deny rule refuses; a
path inside the working directory goes on to the tool's own rules; outside it, a matching Read rule (op
read) or Edit rule (op write) allows; otherwise the call asks. Bracket ranges in a path pattern match
(measured: `claude-[0-9]*` matched `claude-0`). For Bash, the paths a recognised file command (cat, ls, rm,
touch) names and the targets of `>` redirections go through this check BEFORE the Bash allow rules, and an
outside-the-working-directory ask is not one a Bash allow rule can lift: `cat > /tmp/claude-tool-streak-abc.json`
asks although `Bash(cat:*)` and `Bash(cat > /tmp/*.json:*)` both match its text. That is why the
`Bash(cat > /tmp/*...)` and `Bash(rm -f /tmp/*...)` entries are not this lane's: they never granted a /tmp
write, and they are subsumed by `Bash(cat:*)` and `Bash(rm:*)`.
"""
from __future__ import annotations

import ast
import json
import posixpath
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((REPO / "settings.machine.example.json").read_text(encoding="utf-8"))

sys.path.insert(0, str(REPO / "hooks" / "lib"))
from harness_state_dir import _DEFAULT_ROOT as STATE_DEFAULT_ROOT  # noqa: E402

SESSION_ROOT = "/var/tmp/claude-scratch"
ROLE_ROOT = "/tmp/claude-scratch"
SID = "0b0e6c1e-0000-4000-8000-000000000000"
OTHER_SID = "7f7f7f7f-0000-4000-8000-000000000000"
WORKDIR = "/home/u/proj"
SETTINGS_SOURCE = "<home>/.claude"  # user settings: a single leading slash anchors here
SCRATCHPAD_TAIL = "claude-[0-9]*/*/*/scratchpad"


def _layer(base: dict, overlay: dict | None) -> dict:
    """The rendered settings: overlay env replaces, overlay permission entries are appended."""
    env = dict(base["env"])
    perms = {k: list(v) for k, v in base["permissions"].items() if isinstance(v, list)}
    if overlay:
        env.update(overlay.get("env", {}))
        for kind, entries in overlay.get("permissions", {}).items():
            perms.setdefault(kind, [])
            perms[kind] += [e for e in entries if e not in perms[kind]]
    return {"env": env, "permissions": perms}


LAYERS = {"shipped": _layer(SETTINGS, None), "example-overlay": _layer(SETTINGS, EXAMPLE)}
SHIPPED = LAYERS["shipped"]


def scratchpad(tmpdir: str, sid: str = SID) -> str:
    return f"{tmpdir}/claude-0/-home-u-proj/{sid}/scratchpad"


# ------------------------------------------------------------------ the CLI's path-rule match
def _specifiers(perms: dict, tool: str, kind: str) -> list[str]:
    pre = tool + "("
    return [e[len(pre):-1] for e in perms.get(kind, []) if e.startswith(pre) and e.endswith(")")]


def anchored(spec: str) -> str:
    """The absolute pattern a path specifier names: `//p` is absolute, `/p` anchors at the settings
    source, `~/p` at home; a bare name matches at any depth (gitignore), returned as `**/name`."""
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


def _glob_rx(pattern: str) -> str:
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
        elif pattern[i] == "[":
            j = pattern.index("]", i)
            out += "[" + pattern[i + 1:j].replace("\\", "\\\\") + "]"
            i = j + 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return out


def matches(spec: str, path: str) -> bool:
    return re.fullmatch(_glob_rx(anchored(spec)), path) is not None


def decide(perms: dict, op: str, path: str, builtin: bool = False) -> str:
    """allow / ask / deny for a Bash file operand or redirect target, or (builtin=True) for the Read or
    Write tool itself, which a bare tool-wide entry (`Read`) also allows: measured, the bare `Read` lets
    the Read tool read outside the working directory while `cat` of the same file asks."""
    path = posixpath.normpath(path)
    tools = ("Read",) if op == "read" else ("Edit",)
    for tool in ("Read",) if op == "read" else ("Read", "Edit"):
        if any(matches(s, path) for s in _specifiers(perms, tool, "deny")):
            return "deny"
    for tool in tools:
        if any(matches(s, path) for s in _specifiers(perms, tool, "ask")):
            return "ask"
    if path == WORKDIR or path.startswith(WORKDIR + "/"):
        return "allow" if op == "read" else "ask-or-mode"
    for tool in tools:
        if any(matches(s, path) for s in _specifiers(perms, tool, "allow")):
            return "allow"
        if builtin and tool in perms.get("allow", []):
            return "allow"
    return "ask"


# ------------------------------------------------------------------ the harness's own scratch names
def test_session_root_is_the_pinned_tmpdir():
    env = SHIPPED["env"]
    assert env["TMPDIR"] == env["CLAUDE_CODE_TMPDIR"] == SESSION_ROOT
    for hook in ("session-scratch-init.sh", "sessionend-scratch-sweep.sh"):
        assert 'ROOT="${TMPDIR:-/var/tmp/claude-scratch}"' in (REPO / "hooks" / hook).read_text()


def test_role_root_is_the_policy_role_scratch():
    policy = json.loads((REPO / "policies" / "tool-policy.v1.json").read_text())
    prefixes = {p for role in policy["roles"].values() for p in role.get("allowed_write_path_prefixes", [])
                if "claude-scratch" in p}
    assert prefixes, "no role scratch prefix found"
    assert all(re.fullmatch(r"\*/tmp/claude-scratch/[a-z-]+/", p) for p in prefixes), prefixes


@pytest.mark.parametrize("layer", LAYERS)
@pytest.mark.parametrize("tool", ["Read", "Edit"])
def test_exact_scratch_entries_present(layer, tool):
    perms, tmpdir = LAYERS[layer]["permissions"], LAYERS[layer]["env"]["TMPDIR"]
    for spec in (f"/{tmpdir}/{SCRATCHPAD_TAIL}", f"/{tmpdir}/{SCRATCHPAD_TAIL}/**", f"/{ROLE_ROOT}/**"):
        assert f"{tool}({spec})" in perms["allow"], (layer, spec)


@pytest.mark.parametrize("layer", LAYERS)
def test_no_tmp_or_tmpdir_wide_grant(layer):
    """Never /tmp, /var/tmp or the TMPDIR root as a whole: every absolute Read/Edit allow under a temp
    root is one of the exact scratch entries."""
    perms, tmpdir = LAYERS[layer]["permissions"], LAYERS[layer]["env"]["TMPDIR"]
    # The overlay cannot remove a clean-form entry, so the shipped root's pair stays beside its own.
    allowed = {f"{r}/{SCRATCHPAD_TAIL}{tail}" for r in (tmpdir, SESSION_ROOT) for tail in ("", "/**")}
    allowed.add(f"{ROLE_ROOT}/**")
    dirs = [posixpath.normpath(d) for d in perms.get("additionalDirectories", [])]
    assert not [d for d in dirs if d in ("/", "/tmp", "/var", "/var/tmp", tmpdir)
                or d.startswith(("/tmp/", "/var/tmp/", tmpdir + "/"))]
    for tool in ("Read", "Edit"):
        for spec in _specifiers(perms, tool, "allow"):
            pat = anchored(spec)
            if pat.startswith(("/tmp", "/var/tmp", tmpdir)):
                assert pat in allowed, (tool, spec)
    for bad in ("Edit(//tmp/**)", "Read(//tmp/**)", f"Edit(/{tmpdir}/**)", f"Read(/{tmpdir}/**)"):
        assert bad not in perms["allow"]


def test_no_single_slash_path_rule():
    """No Read/Edit allow or deny rule spelled with one leading slash: it would anchor at the settings
    source, so an allow would grant, and a deny would guard, a path under the harness home instead of the
    absolute path it spells (the old `Read(/tmp/**)`).

    The two HOME_ANCHORED_DENY entries are exempt, and `ask` was: OB-L08 shipped one `Edit(/<entry>)` ask per top-level harness-home entry, anchored at the
    settings source on purpose (tests/test_project_write_permissions.py). Ask is checked after deny and
    before allow, so an anchored ask narrows and never grants."""
    perms = SHIPPED["permissions"]
    bad = [f"{t}({s})" for kind in ("allow", "deny") for t in ("Read", "Edit")
           for s in _specifiers(perms, t, kind) if re.match(r"/[^/]", s)]
    assert sorted(bad) == sorted(HOME_ANCHORED_DENY)


# Deny entries anchored at the settings source on purpose: the harness home's venv, whose interpreter the hooks
# run (tests/test_project_write_permissions.py). A deny narrows and never grants, as the ask entries they replace did.
HOME_ANCHORED_DENY = ["Edit(/venv/**)", "Edit(/.venv/**)"]


def test_old_entry_never_reached_tmp():
    assert anchored("/tmp/**") == "<home>/.claude/tmp/**"
    assert not matches("/tmp/**", f"{ROLE_ROOT}/qa/out.txt")
    assert "Read(/tmp/**)" not in SHIPPED["permissions"]["allow"]


def test_state_root_is_not_a_scratch_root():
    for layer in LAYERS.values():
        state_root = layer["env"].get("CLAUDE_STATE_DIR") or STATE_DEFAULT_ROOT
        for root in (layer["env"]["TMPDIR"], ROLE_ROOT):
            assert not (state_root + "/").startswith(root + "/"), (state_root, root)


# ------------------------------------------------------------------ must pass
def must_pass(tmpdir: str):
    s = scratchpad(tmpdir)
    return [
        ("cat <session scratch>/notes.md", "read", f"{s}/notes.md", False),
        ("echo done > <session scratch>/report.md", "write", f"{s}/report.md", False),
        ("ls <session scratch>", "read", s, False),
        ("mkdir -p <session scratch>/sub", "write", f"{s}/sub", False),
        ("Read tool <session scratch>/notes.md", "read", f"{s}/notes.md", True),
        ("Write tool <session scratch>/w.md", "write", f"{s}/w.md", True),
        ("echo done > role scratch", "write", f"{ROLE_ROOT}/qa/out.txt", False),
        ("Write tool role scratch", "write", f"{ROLE_ROOT}/changelog-analyst/commit-msg-1.txt", True),
    ]


PASS_CASES = [(layer, *c) for layer in LAYERS for c in must_pass(LAYERS[layer]["env"]["TMPDIR"])]


@pytest.mark.parametrize("layer,label,op,path,builtin", PASS_CASES, ids=[f"{c[0]}:{c[1]}" for c in PASS_CASES])
def test_scratch_passes(layer, label, op, path, builtin):
    assert decide(LAYERS[layer]["permissions"], op, path, builtin) == "allow", label


# ------------------------------------------------------------------ must still prompt: gate-read files
_STATE_SOURCES = [
    re.compile(r"harness_state_dir\(\)\}?/([A-Za-z0-9_.{}*\-/\[\]]+)"),
    re.compile(r"harness_state_dir\(\)\s*\+\s*['\"]/([^'\"]+)['\"]"),
    re.compile(r"(?:join|Path)\(\s*harness_state_dir\(\)\s*,\s*[fr]?['\"]([^'\"]+)['\"]"),
    re.compile(r"\$\(harness_state_dir\)/([A-Za-z0-9_.{}*\-/$]+)"),
    re.compile(r"(?<![\w./-])/tmp/((?:claude-|agentic-commit|codex-)[A-Za-z0-9_.{}*\-/$]*)"),
]
# A path built from TMPDIR (directly, or through CLAUDE_TMPDIR / DAEMON_RESTART_GRANT_DIR, which default to it).
_TMPDIR_SOURCE = re.compile(
    r"\$\{?(?:TMPDIR|CLAUDE_TMPDIR|DAEMON_RESTART_GRANT_DIR)(?::-[^}]*\}|%/\}|\})?/([A-Za-z0-9_.${}*/-]+)")
_ROLE_SOURCE = re.compile(r"/tmp/claude-scratch/")
# The Python spelling of the same paths (hooks/lib/bash_safety_rules.py builds the daemon-restart flag as
# f"{one_slash(grant_dir)}/claude-allow-daemon-restart-{target}.flag" since P14-5), read from the syntax tree
# of every Python source: an f-string, os.path.join / Path(...) join, `/` join or `+ "/..."` concatenation
# whose base is a TMPDIR root. A root is os.environ / getenv / .get of one of _PY_TMP_ENV, tempfile.gettempdir(),
# a name in _PY_TMP_NAMES, a one-argument wrapper of a root (one_slash, realpath, str, Path), an `or` chain
# holding one, and, per file, a name assigned a root or a dict key whose value is one (`env["grant_dir"]`).
# A name assigned such a path carries it on (`flag + ".lock"`).
_PY_TMP_ENV = frozenset({"TMPDIR", "CLAUDE_TMPDIR", "CLAUDE_DAEMON_RESTART_GRANT_DIR"})
_PY_TMP_NAMES = frozenset({"TMPDIR", "CLAUDE_TMPDIR", "DAEMON_RESTART_GRANT_DIR", "grant_dir"})

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
# Files under TMPDIR a hook or the CLI reads to decide, beside what _TMPDIR_SOURCE finds: each session dir's
# owner record and doc-sync dedupe state (hooks/session-scratch-init.sh, hooks/lib/scratch_owner.py,
# hooks/doc_sync/notice.py: tempfile.gettempdir() is TMPDIR), the daemon flag's lock, the CLI's task outputs.
LISTED_TMPDIR_NAMES = [
    "claude-allow-daemon-restart-default.flag",
    "claude-allow-daemon-restart-default.flag.lock",
    "claude-allow-daemon-restart-{target}.flag",
    "claude-git-blessed/{tok}.grant",
    f"{SID}/.owner",
    f"{OTHER_SID}/.owner",
    f"{OTHER_SID}/doc-sync-notices-main.json",
    f"{SID}/doc-sync-notices-agent-abc.json",
    "runtime-guard-XXXXXX",
    "checkpoint-result.1.ns",
    f"claude-0/-home-u-proj/{SID}/tasks/x.output",
    f"claude-0/-home-u-proj/{OTHER_SID}/tasks/x.output",
]


def _sources() -> list[Path]:
    files = [*REPO.glob("hooks/**/*.py"), *REPO.glob("hooks/**/*.sh"), *REPO.glob("hooks/git-keystone/*"),
             *REPO.glob("scripts/**/*.py"), *REPO.glob("scripts/**/*.sh"), *REPO.glob("scripts/*")]
    return sorted({f for f in files if f.is_file() and "/tests/" not in f.as_posix()})


def _scan(rxs) -> set[str]:
    names: set[str] = set()
    for f in _sources():
        text = f.read_text(encoding="utf-8", errors="ignore")
        for rx in rxs:
            names.update(m.group(1) for m in rx.finditer(text))
    return names


def _callee(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


class _PyTmpPaths:
    """The names a Python module builds under a TMPDIR root, as `{expr}` templates like the shell scan's."""

    def __init__(self, tree: ast.AST):
        self.roots, self.keys, self.paths = set(_PY_TMP_NAMES), set(_PY_TMP_ENV), {}
        assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None]
        dicts = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)]
        changed = True
        while changed:
            before = (len(self.roots), len(self.keys), len(self.paths))
            for a in assigns:
                for t in a.targets if isinstance(a, ast.Assign) else [a.target]:
                    if isinstance(t, ast.Name):
                        if self.is_root(a.value):
                            self.roots.add(t.id)
                        elif (p := self.path_of(a.value)) and t.id not in self.paths:
                            self.paths[t.id] = p
            for d in dicts:
                self.keys |= {k.value for k, v in zip(d.keys, d.values)
                              if isinstance(k, ast.Constant) and isinstance(k.value, str) and self.is_root(v)}
            changed = before != (len(self.roots), len(self.keys), len(self.paths))
        self.names = {p for n in ast.walk(tree) if isinstance(n, ast.expr) and (p := self.path_of(n))}

    def is_root(self, n: ast.AST) -> bool:
        if isinstance(n, ast.Name):
            return n.id in self.roots
        if isinstance(n, ast.Subscript):
            return isinstance(n.slice, ast.Constant) and n.slice.value in self.keys
        if isinstance(n, ast.BoolOp):
            return any(self.is_root(v) for v in n.values)
        if isinstance(n, ast.IfExp):
            return self.is_root(n.body) or self.is_root(n.orelse)
        if isinstance(n, ast.Call):
            name, args = _callee(n), n.args
            if name == "gettempdir":
                return True
            if name in ("get", "getenv") and args and isinstance(args[0], ast.Constant):
                return args[0].value in self.keys
            return name != "join" and len(args) == 1 and self.is_root(args[0])
        return False

    @staticmethod
    def template(n: ast.AST) -> str:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
                           for v in n.values)
        return "{" + ast.unparse(n) + "}"

    def under(self, base: ast.AST, rest: list) -> str | None:
        tail = "/".join(self.template(r) for r in rest)
        if self.is_root(base):
            return tail or None
        head = self.path_of(base)
        return f"{head}/{tail}" if head and tail else None

    def path_of(self, n: ast.AST) -> str | None:
        if isinstance(n, ast.Name):
            return self.paths.get(n.id)
        if isinstance(n, ast.JoinedStr) and n.values and isinstance(n.values[0], ast.FormattedValue):
            rest = self.template(ast.JoinedStr(values=n.values[1:]))
            return (rest[1:] or None) if self.is_root(n.values[0].value) and rest.startswith("/") else None
        if isinstance(n, ast.Call) and n.args:
            name = _callee(n)
            if name in ("join", "Path", "PurePath", "PosixPath") and len(n.args) > 1:
                return self.under(n.args[0], n.args[1:])
            return self.path_of(n.args[0]) if len(n.args) == 1 and name != "join" else None
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            return self.under(n.left, [n.right])
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            if not isinstance(n.right, (ast.Constant, ast.JoinedStr)):
                return None
            right = self.template(n.right)
            if self.is_root(n.left):
                return (right[1:] or None) if right.startswith("/") else None
            head = self.path_of(n.left)
            return head + right if head else None
        return None


def _scan_py_tmpdir(sources: list | None = None) -> set[str]:
    """_PyTmpPaths over every Python source (a .py file or a python shebang) of _sources()."""
    names: set[str] = set()
    for f in sources if sources is not None else _sources():
        text = f.read_text(encoding="utf-8", errors="ignore")
        if f.suffix != ".py" and not re.match(r"#!.*python", text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        names |= _PyTmpPaths(tree).names
    return names


def _instantiate(name: str) -> str:
    name = re.sub(r"\$\{[^}]*\}?|\$[A-Za-z_$]+|\{[^}]*\}?|\[[^\]]*\]", "abc", name)
    name = name.replace("**", "abc").replace("*", "abc").rstrip("/}")
    return name or "abc"


def gate_read_paths(layer: str) -> list[str]:
    env = LAYERS[layer]["env"]
    state_roots = {STATE_DEFAULT_ROOT, env.get("CLAUDE_STATE_DIR") or STATE_DEFAULT_ROOT}
    state = _scan(_STATE_SOURCES) | set(LISTED_STATE_NAMES)
    # The Python scan also finds the CLI scratchpad itself (hooks/pretool-orchestrator-gate.py locates it):
    # that is the scratch this lane grants (must_pass), not a gate-read file, so it is not a must-ask path.
    py_names = {n for n in _scan_py_tmpdir() if not re.fullmatch(r"claude-[^/]+/[^/]+/[^/]+/scratchpad", n)}
    tmp_names = _scan([_TMPDIR_SOURCE]) | py_names | set(LISTED_TMPDIR_NAMES)
    tmpdirs = {env["TMPDIR"], env.get("CLAUDE_CODE_TMPDIR", env["TMPDIR"]), SESSION_ROOT}
    paths = {f"{r}/{_instantiate(n)}" for r in state_roots for n in state}
    paths |= {f"{t}/{_instantiate(n)}" for t in tmpdirs for n in tmp_names}
    return sorted(posixpath.normpath(p) for p in paths)


def test_source_scan_is_not_vacuous():
    state = _scan(_STATE_SOURCES)
    assert "claude-orchestrator-consent-{sid}.flag" in state
    assert "claude-tool-streak-{session_id}.json" in state
    py = _scan_py_tmpdir()
    tmp = _scan([_TMPDIR_SOURCE]) | py
    assert any(n.startswith("claude-allow-daemon-restart-") for n in tmp), tmp
    # The daemon-restart grant and its lock are found in the Python source, not only in LISTED_TMPDIR_NAMES.
    assert {"claude-allow-daemon-restart-{target}.flag", "claude-allow-daemon-restart-{target}.flag.lock"} <= py, py
    assert any(n.startswith("checkpoint-result") for n in tmp), tmp  # S31 removed the blessed-token grants
    assert not [n for n in state if n.split("/")[0] == "claude-scratch"], "state under the role root"


def test_no_hook_builds_a_path_under_the_role_root():
    """The role root is policy-and-prose only: no hook or script composes a path under it."""
    hits = [f.relative_to(REPO).as_posix() for f in _sources()
            if _ROLE_SOURCE.search(f.read_text(encoding="utf-8", errors="ignore"))
            and not f.as_posix().endswith(".conf")]
    assert hits == [], hits


ASK_CASES = [(layer, p) for layer in LAYERS for p in gate_read_paths(layer)]


@pytest.mark.parametrize("layer,path", ASK_CASES, ids=[f"{c[0]}:{c[1]}" for c in ASK_CASES])
def test_gate_read_file_still_asks(layer, path):
    """No path rule covers a hook state or gate-read file: Write, Edit, redirect or touch still asks."""
    perms = LAYERS[layer]["permissions"]
    for tool in ("Read", "Edit"):
        hit = [s for s in _specifiers(perms, tool, "allow") if matches(s, path)]
        assert hit == [], (tool, hit)
    assert decide(perms, "write", path) == "ask"
    assert decide(perms, "write", path, builtin=True) == "ask"


def must_still_ask(tmpdir: str):
    s = scratchpad(tmpdir)
    return [
        ("echo true > /tmp/claude-orchestrator-consent-abc.flag", "/tmp/claude-orchestrator-consent-abc.flag"),
        ("echo '{}' > /tmp/claude-tool-streak-abc.json", "/tmp/claude-tool-streak-abc.json"),
        ("cat > /tmp/claude-tool-streak-abc.json <<EOF", "/tmp/claude-tool-streak-abc.json"),
        ("rm -f /tmp/claude-do-task-abc.json", "/tmp/claude-do-task-abc.json"),
        ("Write tool agentic-commit grant", "/tmp/agentic-commit/push/x/y/main.json"),
        ("echo done > /tmp/probe-report.md", "/tmp/probe-report.md"),
        ("echo > daemon flag", f"{tmpdir}/claude-allow-daemon-restart-default.flag"),
        ("touch daemon flag lock", f"{tmpdir}/claude-allow-daemon-restart-default.flag.lock"),
        ("echo > blessed grant", f"{tmpdir}/claude-git-blessed/tok.grant"),
        ("echo > other-sid .owner", f"{tmpdir}/{OTHER_SID}/.owner"),
        ("doc-sync state", f"{tmpdir}/{OTHER_SID}/doc-sync-notices-main.json"),
        ("CLI task output", f"{tmpdir}/claude-0/-home-u-proj/{SID}/tasks/x.output"),
        ("mktemp file at the TMPDIR root", f"{tmpdir}/runtime-guard-abc"),
        ("traversal out of the scratchpad", f"{s}/../../../../../../../tmp/claude-orchestrator-consent-abc.flag"),
        ("traversal to a sibling's .owner", f"{s}/../../{OTHER_SID}/../../../{OTHER_SID}/.owner"),
        ("a name like the scratchpad beside it", f"{s}x/notes.md"),
        ("a non-uid claude- dir", f"{tmpdir}/claude-git-blessed/a/b/scratchpad/x"),
        ("sibling name of the role root", "/tmp/claude-scratch-userintent-abc.flag"),
        ("the /var/tmp graphify cache", "/var/tmp/claude-graphify/x"),
    ]


STILL_ASK = [(layer, *c) for layer in LAYERS for c in must_still_ask(LAYERS[layer]["env"]["TMPDIR"])]


@pytest.mark.parametrize("layer,label,path", STILL_ASK, ids=[f"{c[0]}:{c[1]}" for c in STILL_ASK])
def test_named_cases_still_ask(layer, label, path):
    perms = LAYERS[layer]["permissions"]
    assert decide(perms, "write", path) == "ask", label
    assert decide(perms, "write", path, builtin=True) == "ask", label


# ------------------------------------------------------------------ what the CLI did (2.1.326)
# Each case driven once through the installed CLI, headless, default permission mode, the settings file's
# `permissions` block as the throwaway HOME's user settings, CLAUDE_CODE_TMPDIR=/var/tmp/claude-scratch.
# Columns: base (d1abc798), this lane's first commit (`Read/Edit(//var/tmp/claude-scratch/**)`), the fix.
MEASURED = {
    # label: (path, op, builtin, base, first commit, fix)
    "cat scratch": (f"{scratchpad(SESSION_ROOT)}/notes.md", "read", False, "ask", "ran", "ran"),
    "echo > scratch": (f"{scratchpad(SESSION_ROOT)}/report.md", "write", False, "ask", "ran", "ran"),
    "ls scratch": (scratchpad(SESSION_ROOT), "read", False, "ask", "ran", "ran"),
    "Read tool scratch": (f"{scratchpad(SESSION_ROOT)}/notes.md", "read", True, "ran", "ran", "ran"),
    "Write tool scratch": (f"{scratchpad(SESSION_ROOT)}/w.md", "write", True, "ask", "ran", "ran"),
    "echo > role scratch": (f"{ROLE_ROOT}/qa/out.txt", "write", False, "ask", "ran", "ran"),
    "Write tool role scratch": (f"{ROLE_ROOT}/qa/w.txt", "write", True, "ask", "ran", "ran"),
    "echo > consent flag": ("/tmp/claude-orchestrator-consent-abc.flag", "write", False, "ask", "ask", "ask"),
    "echo > streak": ("/tmp/claude-tool-streak-abc.json", "write", False, "ask", "ask", "ask"),
    "Write tool consent flag": ("/tmp/claude-orchestrator-consent-abc.flag", "write", True, "ask", "ask", "ask"),
    "Write tool daemon flag": (f"{SESSION_ROOT}/claude-allow-daemon-restart-default.flag", "write", True,
                               "ask", "ran", "ask"),
    "echo > daemon flag": (f"{SESSION_ROOT}/claude-allow-daemon-restart-default.flag", "write", False,
                           "ask", "ran", "ask"),
    "touch daemon flag lock": (f"{SESSION_ROOT}/claude-allow-daemon-restart-default.flag.lock", "write", False,
                               "ask", "ran", "ask"),
    "Write tool blessed grant": (f"{SESSION_ROOT}/claude-git-blessed/tok.grant", "write", True, "ask", "ran", "ask"),
    "echo > blessed grant": (f"{SESSION_ROOT}/claude-git-blessed/tok.grant", "write", False, "ask", "ran", "ask"),
    "Write tool other-sid .owner": (f"{SESSION_ROOT}/other-sid/.owner", "write", True, "ask", "ran", "ask"),
    "echo > other-sid .owner": (f"{SESSION_ROOT}/other-sid/.owner", "write", False, "ask", "ran", "ask"),
    "Write tool doc-sync state": (f"{SESSION_ROOT}/other-sid/doc-sync-notices-main.json", "write", True,
                                  "ask", "ran", "ask"),
    "Write tool CLI task output": (f"{SESSION_ROOT}/claude-0/-probe-proj/probe-sid/tasks/x.output", "write", True,
                                   "ask", "ran", "ask"),
    "Write tool TMPDIR-root file": (f"{SESSION_ROOT}/runtime-guard-abc", "write", True, "ask", "ran", "ask"),
}


@pytest.mark.parametrize("label", MEASURED)
def test_model_agrees_with_measurement(label):
    path, op, builtin, _base, _first, fix = MEASURED[label]
    assert decide(SHIPPED["permissions"], op, path, builtin) == ("allow" if fix == "ran" else "ask"), label
