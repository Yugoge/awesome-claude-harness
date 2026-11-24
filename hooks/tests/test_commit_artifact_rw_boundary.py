r"""READ/WRITE BOUNDARY GUARD — the two commit-artifact raw-write layers.

WHY THIS FILE EXISTS
────────────────────
`pretool-bash-safety.sh` carries two sibling layers that protect the two
commit-pipeline evidence namespaces: the changelog-analyst dispatch
attestation (refusal label `commit-dispatch-attestation-write`) and the
privilege-guard grant the attestation exists to qualify (refusal label
`commit-grant-raw-write`).

Both were built as a single predicate: "a write verb appears SOMEWHERE in the
command AND the namespace appears SOMEWHERE in the command". That predicate
over-blocked every READ of the namespace that handles its own error stream,
because a stream redirection such as `2>/dev/null` supplied the operator all
by itself — so an auditor could not list or read the very artifacts that carry
the security claim. Both layers were repaired into two OR'd branches:

  branch 1 (redirection)  the namespace must IMMEDIATELY follow the
                          redirection operator, i.e. the operator's TARGET is
                          the namespace rather than merely co-present with it;
  branch 2 (unbound)      retained only for write verbs that take their
                          destination as an ARGUMENT, where there is no
                          redirection operator to bind.

Nothing pinned that boundary. The over-block could silently return — by
re-merging the branches, by dropping branch 1's target anchor, or by narrowing
branch 2 — and every existing test would have stayed green. This file is that
pin: it drives the REAL hook process and asserts both polarities (reads
PERMITTED, writes REFUSED) for both layers.

A SECOND, INDEPENDENT HOLE IS ALSO PINNED HERE
──────────────────────────────────────────────
The grant layer originally had NO interpreter verbs in branch 2 at all, which
left the grant namespace less protected than the attestation namespace it
qualifies: an interpreter writes a file with NO redirection operator
whatsoever, so branch 1 cannot see it and branch 2 is the only thing that can.
`test_interpreter_verbs_*` asserts, per layer, that branch 2's verb list is
non-empty and still contains every interpreter, so a future narrowing that
drops one fails here instead of silently reopening the hole.

NOTHING IS HARDCODED, AND NOTHING IS WRITTEN
────────────────────────────────────────────
Three derivations, no mirrored constants (a sibling constant in this same area
of a hook is easy to hand-mirror with nothing binding the copies):

  * the attestation filename prefix comes from the named production constant
    `hooks/lib/commit_pipeline.py::ATTEST_PREFIX`, which the hook's own
    comment declares to be its source;
  * the grant filename prefix is AST-extracted from the canonical minter
    `scripts/write-commit-grant.py`, at the statement that composes the grant
    path — production's own source of truth for that filename;
  * the state ROOT comes from running the production shell library
    `hooks/lib/harness_state_dir.sh::harness_state_dir`, the same function the
    hook itself calls.

`test_hook_prefix_literal_matches_production_*` then asserts the hook refuses
exactly the Python-derived prefix. That is the drift tie: rename
a prefix on either side alone and these tests FAIL loudly, rather than
quietly re-targeting themselves at a namespace nobody protects.

Every probe is aimed at a REDIRECTED state root (`CLAUDE_STATE_DIR` pointed at
a pytest sandbox), and `test_redirection_actually_moved_the_root` proves the
redirection took effect rather than assuming it: the sandbox path IS refused,
the default-root path is NOT refused by that layer while redirected, and a
positive control with the variable unset shows the default-root path IS
refused — so the "not refused" result cannot be a method that simply never
returns a hit. `test_zz_no_artifact_was_ever_written` confirms the real
namespaces were never touched; the hook is a PreToolUse gate that inspects a
command string and never executes it, so every probe below is inert text.

SAFETY: this file's own source never types either namespace prefix — same
convention as test_fail_closed_drift.py. That is not cosmetic: a shell probe
batch that DID type the attestation prefix in its own command line was itself
refused by the layer under test (label `commit-dispatch-attestation-write`,
exit 2), which is precisely why the prefixes must be derived at runtime.

Run with: python3 -m pytest hooks/tests/test_commit_artifact_rw_boundary.py -v
"""
import ast
import glob
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(HOOKS_DIR, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
STATE_DIR_LIB = os.path.join(HOOKS_DIR, "lib", "harness_state_dir.sh")
GRANT_MINTER = os.path.join(REPO_ROOT, "scripts", "write-commit-grant.py")

sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))
sys.path.insert(0, HOOKS_DIR)  # the rules module imports `lib.*`; its own path setup reads argv, which is pytest's here

from commit_pipeline import ATTEST_PREFIX  # noqa: E402
import bash_safety_rules  # noqa: E402

RULES = os.path.join(HOOKS_DIR, "lib", "bash_safety_rules.py")
with open(RULES) as _fp:
    HOOK_SRC = _fp.read()
HOOK_LINES = HOOK_SRC.splitlines()

BLOCK = 2
ALLOW = 0

# The shell variables the hook uses for the two namespaces. These are variable
# NAMES, not namespace values -- the values are derived below.
ATTEST_VAR = "attestation"
GRANT_VAR = "grant"

# The one list deliberately spelled out: AC6's whole point is that THESE names
# must stay in branch 2 of BOTH layers. An interpreter writes with no
# redirection operator at all, so branch 1 is blind to it and branch 2 is the
# only thing standing in the way. Deriving this list from the hook would make
# the assertion vacuous -- it would pass no matter what the hook dropped.
INTERPRETERS = frozenset({"python", "awk", "perl", "node", "ruby"})


# ── derivation 1: the state root, from the production shell library ─────────
def harness_state_dir(state_dir_value):
    """Call the production `harness_state_dir` the hook itself sources.

    `state_dir_value=None` => CLAUDE_STATE_DIR removed from the environment,
    yielding the default root.
    """
    env = os.environ.copy()
    if state_dir_value is None:
        env.pop("CLAUDE_STATE_DIR", None)
    else:
        env["CLAUDE_STATE_DIR"] = state_dir_value
    proc = subprocess.run(
        ["bash", "-c", '. "$1" && harness_state_dir', "_", STATE_DIR_LIB],
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, f"state-dir library failed: {proc.stderr}"
    return proc.stdout.strip()


DEFAULT_STATE_ROOT = harness_state_dir(None)


# ── derivation 2: the grant filename prefix, from the canonical minter ──────
def _grant_prefix_from_minter():
    """AST-extract the grant filename prefix from scripts/write-commit-grant.py.

    The minter composes `Path(args.output_dir) / f"<prefix>{sid}-{nonce}.json"`.
    The leading constant chunk of that f-string is production's source of truth
    for the grant filename; this test must not restate it.
    """
    with open(GRANT_MINTER) as fp:
        tree = ast.parse(fp.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "grant_path" for t in node.targets
        ):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.JoinedStr) and sub.values:
                head = sub.values[0]
                if isinstance(head, ast.Constant) and isinstance(head.value, str):
                    return head.value
    raise AssertionError(
        "could not AST-derive the grant filename prefix from "
        f"{GRANT_MINTER}: no `grant_path = ... f'...'` assignment found. "
        "The minter was restructured; re-point this derivation at its new "
        "source of truth rather than hardcoding a prefix here."
    )


GRANT_PREFIX = _grant_prefix_from_minter()


# ── the rule's line, for messages ───────────────────────────────────────────
PREDICATE_LINENO = next(i for i, line in enumerate(HOOK_LINES, 1) if line.startswith("def writes_namespace("))


# ── derivation 4: the SHARED verb alternation, from its ONE definition ──────
# Both layers evaluate one predicate, lib/bash_safety_rules.py::writes_namespace,
# over one verb alternation, ARTIFACT_WRITE_VERB_RE. This derivation reads that
# constant; the tests below assert no second copy exists and both layers call
# the one predicate.
VERB_VAR = "ARTIFACT_WRITE_VERB_RE"
VERB_ALT_LINENO = next(i for i, line in enumerate(HOOK_LINES, 1) if line.startswith(VERB_VAR + " = "))
VERB_ALT = bash_safety_rules.ARTIFACT_WRITE_VERB_RE[1:-1]
# Branch 1 of the predicate: a redirection whose TARGET is the namespace.
REDIRECT_BRANCH = """grep(r\"\"\">>?[&|]?\\s*['"]?\"\"\" + ns_re, command)"""
# Branch 2: a listed verb HANDED the namespace.
BOUND_BRANCH2 = 'grep(ARTIFACT_WRITE_VERB_RE + ".*" + ns_re, one)'


def _layer_calls():
    """The writes_namespace calls of commit_artifact_rules, one per protected namespace."""
    body = HOOK_SRC[HOOK_SRC.index("def commit_artifact_rules("):]
    body = body[:body.index("\ndef ", 1)]
    return re.findall(r"writes_namespace\(command, re\.escape\(base \+ \"/\" \+ (\w+|\"[^\"]+\")\)\)", body)


# Branch 2's verbs are ANCHORED -- `\bVERB([^A-Za-z_]|$)`, some carrying an
# optional real-binary-alias group (`cp(io)?`, `i?python`, `[gmn]?awk`,
# `node(js)?`). That shape puts a `|` INSIDE a group, so the alternation can
# only be split at paren depth 0: a flat `alt.split("|")` shreds every token
# into fragments like `$)` and `tee([^A-Za-z_]`.
#
# The right bound runs to the end of the shell word and refuses a `/` before
# it, so a DIRECTORY named like a verb (`node20`, `python3-x`, a home directory
# named node) is not read as a launch.
# OLD_BOUNDARY_SUFFIX is the bound before that change; the T1-1 tests below
# restore it on a throwaway copy as their positive control.
BOUNDARY_SUFFIX = "([^A-Za-z_/][-0-9A-Za-z._+@%~:=#^]*)?([^-/0-9A-Za-z._+@%~:=#^]|$)"
OLD_BOUNDARY_SUFFIX = "([^A-Za-z_]|$)"
_OPTIONAL_GROUP = re.compile(r"(?:\([A-Za-z0-9]+\)|\[[^]]+\]|[A-Za-z0-9])\?")


def _split_alternation(alt):
    """Split a regex alternation on its TOP-LEVEL `|` only.

    Depth- and bracket-expression-aware, so neither the `|` in the trailing
    boundary class nor one inside an alias group is mistaken for a separator.
    """
    parts, buf, depth, in_class, i = [], [], 0, False, 0
    while i < len(alt):
        c = alt[i]
        if c == "\\" and i + 1 < len(alt):
            buf.append(alt[i : i + 2])
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def _normalize_verb(token):
    """Turn a regex alternation token into a runnable command head.

    Strips the anchors back off -- the leading `\\b`, the trailing boundary
    class, and any optional alias group -- to recover the bare verb.
    """
    t = token.replace(r"\b", "")
    if t.endswith(BOUNDARY_SUFFIX):
        t = t[: -len(BOUNDARY_SUFFIX)]
    t = _OPTIONAL_GROUP.sub("", t)
    t = t.replace(r"\s+", " ")
    t = t.replace(r"\s", "")
    return t.strip()


def _layer_verbs(var):
    alt = VERB_ALT
    return [
        _normalize_verb(tok)
        for tok in _split_alternation(alt)
        if _normalize_verb(tok)
    ]


def _deanchored(alt):
    """The pre-anchoring shape of an alternation, DERIVED from the live one.

    Removing the leading `\\b` and the trailing boundary class is exactly the
    mutation that reinstates the prose-collision over-block, so the control in
    `test_prose_word_collisions_are_permitted` is derived from production
    rather than restating a pattern that could drift.
    """
    return alt.replace(BOUNDARY_SUFFIX, "").replace(r"\b", "")


# ── the two layers under test, fully derived ────────────────────────────────
class Layer:
    def __init__(self, name, label, var, prefix):
        self.name = name
        self.label = label
        self.var = var
        self.prefix = prefix
        self.lineno, self.redirect_branch = PREDICATE_LINENO, REDIRECT_BRANCH
        self.verbs = _layer_verbs(var)

    def path(self, state_root):
        """An artifact path inside `state_root`'s protected namespace."""
        return os.path.join(state_root, f"{self.prefix}sid-nonce.json")

    def __repr__(self):
        return f"<Layer {self.name}>"


ATTEST_LAYER = Layer(
    "attestation", "commit-dispatch-attestation-write", ATTEST_VAR, ATTEST_PREFIX
)
GRANT_LAYER = Layer(
    "grant", "commit-grant-raw-write", GRANT_VAR, GRANT_PREFIX
)
LAYERS = [ATTEST_LAYER, GRANT_LAYER]
LAYER_IDS = [lyr.name for lyr in LAYERS]


# ── the probe harness ───────────────────────────────────────────────────────
def run_hook(command, state_root):
    """Feed one Bash tool_input to the real hook. Nothing is ever executed."""
    env = os.environ.copy()
    env["CLAUDE_STATE_DIR"] = state_root
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["bash", HOOK], input=payload, env=env, text=True, capture_output=True
    )
    return proc.returncode, proc.stderr


def _write_mutant(tmp_path, name, src):
    """A throwaway hooks tree whose rules module is `src`; every other file links to the live one."""
    root = tmp_path / name
    (root / "lib").mkdir(parents=True)
    for entry in os.listdir(HOOKS_DIR):
        if entry not in ("lib", "tests", "__pycache__"):
            (root / entry).symlink_to(os.path.join(HOOKS_DIR, entry))
    for entry in os.listdir(os.path.join(HOOKS_DIR, "lib")):
        if entry not in ("bash_safety_rules.py", "__pycache__"):
            (root / "lib" / entry).symlink_to(os.path.join(HOOKS_DIR, "lib", entry))
    (root / "lib" / "bash_safety_rules.py").write_text(src)
    return str(root / "pretool-bash-safety.sh")


def refusal_labels(stderr):
    """Every refusal label present in a hook's stderr.

    AC3: a refusal from an unrelated layer must never be creditable to the
    layer under test, so assertions compare LABELS, never bare exit codes.
    """
    return set(re.findall(r"BLOCKED: ([a-z0-9-]+)", stderr))


@pytest.fixture(scope="module")
def state_root(tmp_path_factory):
    """A redirected state root, with the redirection itself verified."""
    sandbox = str(tmp_path_factory.mktemp("state"))
    resolved = harness_state_dir(sandbox)
    assert resolved == sandbox, (
        "the production state-dir library did not honour CLAUDE_STATE_DIR: "
        f"asked for {sandbox}, got {resolved}"
    )
    assert resolved != DEFAULT_STATE_ROOT, (
        "sandbox collided with the real default state root; probes would be "
        "aimed at live artifacts"
    )
    for lyr in LAYERS:
        assert not lyr.path(resolved).startswith(
            os.path.join(DEFAULT_STATE_ROOT, lyr.prefix)
        ), f"{lyr.name}: sandbox probe path still falls inside the real namespace"
    return resolved


# ── AC1: read-shaped commands naming the namespace are PERMITTED ────────────
READ_SHAPES = [
    ("bare-listing", "ls -1 {p}"),
    ("plain-read", "cat {p}"),
    ("read-suppressing-own-stderr", "cat {p} 2>/dev/null"),
    ("read-merging-stderr-into-stdout", "cat {p} 2>&1"),
    # The exact shape the pre-repair predicate refused, which is what made the
    # artifact carrying the security claim un-auditable from Bash.
    ("long-listing-suppressing-own-stderr", "ls -la {p} 2>/dev/null"),
    # ── the WIDER half of the same over-block ───────────────────────────────
    # A verb that merely appears ANYWHERE in the command, for any reason, is
    # not one HANDED the namespace. Every shape below is fully read-only; the
    # natural auditing shape is the first two: list the namespace, parse the
    # JSON with a one-liner.
    ("listing-piped-to-version-suffixed-python", "ls -1 {p} 2>/dev/null | python3 -c 'import sys; print(len(sys.stdin.read()))'"),
    ("read-piped-to-dotted-python-jsontool", "cat {p} 2>/dev/null | python3.12 -m json.tool"),
    ("jq-read-piped-to-python", "jq -r .minted_by {p} | python3 -c 'print(1)'"),
    ("listing-piped-to-awk-positional", "ls -l {p} | awk '{{print $1}}'"),
    ("read-piped-to-perl-oneliner", "cat {p} | perl -ne 'print'"),
    ("listing-piped-to-count", "ls -1 {p} | wc -l"),
    # Reading through a shell variable must stay permitted: branches 3 and 4
    # fire on a WRITE through the variable, never on a read through one.
    ("variable-captured-then-read", "NS={p}; ls -l \"$NS\" 2>/dev/null"),
    ("variable-captured-then-read-piped-to-python", "NS={p}; cat \"$NS\" | python3 -c 'import sys; print(len(sys.stdin.read()))'"),
    ("variable-captured-then-read-piped-to-awk", "NS={p}; ls -l $NS | awk '{{print $1}}'"),
]


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize("shape,tmpl", READ_SHAPES, ids=[s for s, _ in READ_SHAPES])
def test_read_shaped_command_is_permitted(layer, shape, tmpl, state_root):
    cmd = tmpl.format(p=layer.path(state_root))
    rc, err = run_hook(cmd, state_root)
    assert layer.label not in refusal_labels(err), (
        f"{layer.name} layer (hook line {layer.lineno}) refused a READ: {cmd}\n"
        f"The over-block is back. stderr:\n{err}"
    )
    assert rc == ALLOW, (
        f"read probe was refused by another layer: {cmd}\n"
        f"labels={sorted(refusal_labels(err))} rc={rc}\n{err}"
    )


# ── AC2: write-shaped commands whose DESTINATION is the namespace: REFUSED ──
WRITE_SHAPES = [
    ("plain-redirection", "echo x > {p}"),
    ("no-space-redirection", "echo x >{p}"),
    ("append", "echo x >> {p}"),
    ("no-space-append", "echo x >>{p}"),
    ("stdout-numbered-descriptor", "echo x 1> {p}"),
    ("stderr-numbered-descriptor", "echo x 2> {p}"),
    ("stdout-numbered-append", "echo x 1>> {p}"),
    ("stderr-numbered-append", "echo x 2>> {p}"),
    ("both-streams-ampersand-first", "echo x &> {p}"),
    ("both-streams-ampersand-second", "echo x >& {p}"),
    ("both-streams-append", "echo x &>> {p}"),
    ("clobber-override", "echo x >| {p}"),
    ("single-quoted-destination", "echo x > '{p}'"),
    ("double-quoted-destination", 'echo x > "{p}"'),
]


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize("shape,tmpl", WRITE_SHAPES, ids=[s for s, _ in WRITE_SHAPES])
def test_write_shaped_redirection_is_refused(layer, shape, tmpl, state_root):
    cmd = tmpl.format(p=layer.path(state_root))
    rc, err = run_hook(cmd, state_root)
    labels = refusal_labels(err)
    assert layer.label in labels, (
        f"{layer.name} layer (hook line {layer.lineno}) did NOT refuse a write "
        f"whose destination is its namespace: {cmd}\n"
        f"labels={sorted(labels)} rc={rc}\n{err}"
    )
    assert rc == BLOCK, f"{cmd}: expected exit {BLOCK}, got {rc}"


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_destination_as_argument_verbs_are_refused(layer, state_root):
    """Branch 2, verb by verb — every verb the hook itself lists.

    Each probe contains NO redirection operator, so branch 1 cannot possibly
    match it: a refusal here is attributable to branch 2 alone.
    """
    assert layer.verbs, f"{layer.name}: branch 2's verb list parsed as empty"
    path = layer.path(state_root)
    unreachable = []
    for verb in layer.verbs:
        cmd = f"{verb} {path}"
        assert ">" not in cmd, f"probe for {verb!r} leaked a redirection operator"
        rc, err = run_hook(cmd, state_root)
        labels = refusal_labels(err)
        if layer.label not in labels:
            unreachable.append((verb, rc, sorted(labels)))
    assert not unreachable, (
        f"{layer.name} layer (hook line {layer.lineno}): branch 2 did not "
        f"refuse these verbs under its own label — either the verb left the "
        f"list, or an earlier layer shadows the probe (report it as "
        f"unreachable, never widen the hook to reach it): {unreachable}"
    )


# ── AC3: no unrelated layer may masquerade as the layer under test ──────────
@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_refusal_is_not_creditable_to_the_sibling_layer(layer, state_root):
    """A write into one namespace must not be refused by the other's label."""
    sibling = next(other for other in LAYERS if other is not layer)
    rc, err = run_hook(f"echo x > {layer.path(state_root)}", state_root)
    labels = refusal_labels(err)
    assert layer.label in labels, f"{layer.name}: own label missing; rc={rc}\n{err}"
    assert sibling.label not in labels, (
        f"a write into the {layer.name} namespace was also refused by the "
        f"{sibling.name} label — the two namespaces overlap, so neither "
        f"layer's assertions prove anything. labels={sorted(labels)}"
    )


def test_label_detector_can_both_hit_and_miss(state_root):
    """Positive control for every 'label absent' assertion in this file.

    Without this, a `refusal_labels()` that silently returned the empty set
    would make all AC1 permits pass vacuously.
    """
    _, hit_err = run_hook(f"echo x > {GRANT_LAYER.path(state_root)}", state_root)
    assert GRANT_LAYER.label in refusal_labels(hit_err), (
        "the detector returned no label for a command the hook demonstrably "
        f"refuses; it cannot be trusted to report absence. stderr:\n{hit_err}"
    )
    miss_rc, miss_err = run_hook("echo hello", state_root)
    assert refusal_labels(miss_err) == set(), (
        f"benign command produced labels: {sorted(refusal_labels(miss_err))}"
    )
    assert miss_rc == ALLOW


# ── AC4: the drift tie between the hook and the production constants ────────
def _refuses_exactly_the_prefix(layer, state_root):
    """The layer refuses a write at its production prefix and not at a sibling one letter off."""
    hit = os.path.join(state_root, f"{layer.prefix}sid-nonce.json")
    sibling = os.path.join(state_root, f"{layer.prefix[:-2]}X-sid-nonce.json")
    return (layer.label in refusal_labels(run_hook(f"echo x > {hit}", state_root)[1]),
            layer.label in refusal_labels(run_hook(f"echo x > {sibling}", state_root)[1]))


def test_hook_prefix_literal_matches_production_attest_constant(state_root):
    assert _refuses_exactly_the_prefix(ATTEST_LAYER, state_root) == (True, False), (
        "the attestation rule no longer refuses exactly commit_pipeline.ATTEST_PREFIX; "
        "every probe in this file would otherwise have silently re-targeted itself."
    )


def test_hook_prefix_literal_matches_production_grant_minter(state_root):
    assert _refuses_exactly_the_prefix(GRANT_LAYER, state_root) == (True, False), (
        f"the grant rule no longer refuses exactly the prefix the canonical minter {GRANT_MINTER} "
        "writes; a hand-authored grant at the minter's filename would pass."
    )


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_layer_binds_redirection_operator_to_its_target(layer):
    """Branch 1 must anchor the namespace to the operator, not merely co-occur.

    This is the repair itself. If the namespace reference stops being the tail
    of branch 1's pattern, the unbound predicate is back and every read that
    handles its own error stream is refused again.
    """
    assert layer.redirect_branch, (
        f"{layer.name} layer (hook line {layer.lineno}): no redirection branch "
        "whose pattern ENDS at the namespace reference was found. Branch 1 "
        "either vanished or stopped binding the operator to its target."
    )
    assert layer.redirect_branch in HOOK_SRC
    assert layer.redirect_branch.endswith('" + ns_re, command)')
    operator_part = layer.redirect_branch[: -len('" + ns_re, command)')]
    assert ">" in operator_part, (
        f"{layer.name}: branch 1 no longer carries a redirection operator "
        f"ahead of the namespace: {layer.redirect_branch!r}"
    )


# ── AC5: the redirection of the state root actually took effect ─────────────
@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_redirection_actually_moved_the_root(layer, state_root):
    """Three measurements, so 'not refused' cannot be a method that never hits.

    1. redirected root  -> REFUSED under this layer's label (it honours the var)
    2. default root while redirected -> NOT refused by this layer (root moved)
    3. default root with the var unset -> REFUSED (the control proving step 2's
       negative result came from a method that CAN return a hit)
    """
    redirected = f"echo x > {layer.path(state_root)}"
    rc1, err1 = run_hook(redirected, state_root)
    assert layer.label in refusal_labels(err1), (
        f"{layer.name} ignores CLAUDE_STATE_DIR; rc={rc1}\n{err1}"
    )

    # The default root lies under HOME, which each test moves (conftest): resolve it under this test's HOME.
    default_path = layer.path(harness_state_dir(None))
    default_cmd = f"echo x > {default_path}"
    _, err2 = run_hook(default_cmd, state_root)
    assert layer.label not in refusal_labels(err2), (
        f"{layer.name} refused a DEFAULT-root path while the state root was "
        f"redirected to {state_root}. The redirection did not take effect, so "
        "every other probe in this file may have been hitting the real "
        f"namespace. stderr:\n{err2}"
    )

    env = os.environ.copy()
    env.pop("CLAUDE_STATE_DIR", None)
    proc = subprocess.run(
        ["bash", HOOK],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": default_cmd}}
        ),
        env=env,
        text=True,
        capture_output=True,
    )
    assert layer.label in refusal_labels(proc.stderr), (
        f"{layer.name}: positive control failed — with CLAUDE_STATE_DIR unset, "
        f"a write to the default root was NOT refused, so the negative result "
        f"above proves nothing. stderr:\n{proc.stderr}"
    )


# ── anti-vacuity: the AC1 permits would FAIL if the repair were reverted ────
@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_reverting_the_repair_would_be_caught(layer, state_root, tmp_path):
    """Positive control for every 'read is permitted' assertion above.

    A permit that passes because the layer never fires on anything would be
    worthless. This reverts the repair on a THROWAWAY COPY of the hook —
    branch 1's target-bound pattern is replaced by the bare redirection
    operator, which is the pre-repair unbound predicate — and asserts the
    read-shaped probe is then REFUSED. So the permits above are load-bearing:
    they pass because of the two-branch structure, not by accident.

    The real hook is never read-write opened, never modified, and never
    re-pointed; the copy lives in pytest's tmp_path and is discarded.
    """
    bound = layer.redirect_branch
    assert bound in HOOK_SRC, (
        f"{layer.name}: could not locate branch 1's text to revert; "
        f"parsed pattern was {layer.redirect_branch!r}"
    )
    reverted_src = HOOK_SRC.replace(bound, 'grep(r">", command)', 1)
    assert reverted_src != HOOK_SRC, "mutation was a no-op"

    mutant = _write_mutant(tmp_path, "reverted", reverted_src)

    probe = f"ls -la {layer.path(state_root)} 2>/dev/null"
    env = os.environ.copy()
    env["CLAUDE_STATE_DIR"] = state_root
    proc = subprocess.run(
        ["bash", mutant],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": probe}}),
        env=env,
        text=True,
        capture_output=True,
    )
    assert layer.label in refusal_labels(proc.stderr), (
        f"{layer.name}: reverting branch 1 to the unbound predicate did NOT "
        "reproduce the over-block, so the read-permit assertions in this file "
        "are not actually pinning the repair. Re-derive the mutation before "
        f"trusting them. rc={proc.returncode} stderr:\n{proc.stderr}"
    )

    # And the real hook, on the same probe, permits it.
    rc, err = run_hook(probe, state_root)
    assert layer.label not in refusal_labels(err) and rc == ALLOW, (
        f"{layer.name}: live hook refused the probe the mutant was built to "
        f"contrast against. rc={rc}\n{err}"
    )


# ── AC6: branch 2 still carries the interpreters, in BOTH layers ────────────
@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_interpreter_verbs_are_present_in_branch_two(layer):
    assert layer.verbs, (
        f"{layer.name} layer (hook line {layer.lineno}): branch 2's verb list "
        "is EMPTY. Every destination-as-argument write now passes."
    )
    missing = sorted(INTERPRETERS - set(layer.verbs))
    assert not missing, (
        f"{layer.name} layer (hook line {layer.lineno}) dropped interpreters "
        f"{missing} from branch 2. An interpreter writes with no redirection "
        "at all, so branch 1 cannot see it — dropping one reopens exactly the "
        f"hole this layer exists to close. Present: {sorted(layer.verbs)}"
    )


# ── the prose-collision over-block, pinned so it cannot silently return ─────
# Branch 2's verb tokens were bare, UNANCHORED substrings, so an ordinary
# English word containing a verb as an internal or trailing fragment supplied
# the "write verb" by itself and a pure READ of the namespace was refused --
# measured on BOTH layers for every word below. The anchors are what make
# these permits possible; `_unanchored_mutant` is the control proving it.
PROSE_COLLISIONS = [
    ("untouched-vs-touch", "touch", "grep -l untouched {p}"),
    ("nodes-vs-node", "node", "grep -c nodes {p}"),
    ("awkward-vs-awk", "awk", "grep -n awkward {p}"),
    ("reinstall-vs-install", "install", "grep -i reinstall {p}"),
    ("committee-vs-tee", "tee", "grep -c committee {p}"),
]

# A MEASURED NON-COLLISION, recorded so nobody "restores" it as evidence:
# `between` does NOT contain `tee` -- it is be-tween, i.e. `twee` -- so it
# never collided, and the unanchored mutant permits it too. `committee`
# (commit-tee) is the real `tee` collision.
NON_COLLIDING_WORD = "between"


def _run(hook, command, state_root):
    """Drive an ARBITRARY hook copy; `run_hook` only drives the live one."""
    env = os.environ.copy()
    env["CLAUDE_STATE_DIR"] = state_root
    proc = subprocess.run(
        ["bash", hook],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": command}}
        ),
        env=env,
        text=True,
        capture_output=True,
    )
    return proc.returncode, proc.stderr


def _unanchored_mutant(tmp_path, layer):
    """A throwaway copy of the hook with the branch-2 verb anchors gone.

    Now that the alternation is defined ONCE and shared, this de-anchors BOTH
    layers at the single definition -- which is fine for a control: the
    assertion it supports only ever reads the layer under test.

    The real hook is never opened read-write, never modified and never
    re-pointed; the copy lives in pytest's tmp_path and is discarded.
    """
    src = _rebind_verbs(_deanchored(VERB_ALT))
    return _write_mutant(tmp_path, f"unanchored-{layer.name}", src)


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize(
    "case,verb,tmpl", PROSE_COLLISIONS, ids=[c for c, _, _ in PROSE_COLLISIONS]
)
def test_prose_word_collisions_are_permitted(
    layer, case, verb, tmpl, state_root, tmp_path
):
    """A pure READ naming the namespace must survive an English word."""
    cmd = tmpl.format(p=layer.path(state_root))
    assert ">" not in cmd, f"probe for {case} leaked a redirection operator"
    rc, err = run_hook(cmd, state_root)
    assert layer.label not in refusal_labels(err), (
        f"{layer.name} layer (hook line {layer.lineno}) refused a pure READ "
        f"because an ordinary English word supplied the {verb!r} token: {cmd}\n"
        f"Branch 2's verb alternation lost its anchors. stderr:\n{err}"
    )
    assert rc == ALLOW, (
        f"read probe was refused by another layer: {cmd}\n"
        f"labels={sorted(refusal_labels(err))} rc={rc}\n{err}"
    )

    # Positive control: the SAME probe against a de-anchored copy IS refused,
    # so the permit above is load-bearing and not a method that can never hit.
    mrc, merr = _run(_unanchored_mutant(tmp_path, layer), cmd, state_root)
    assert layer.label in refusal_labels(merr), (
        f"{layer.name}: de-anchoring branch 2 did NOT reproduce the {verb!r} "
        f"over-block for {case}, so this permit proves nothing. Re-derive the "
        f"mutation before trusting it. rc={mrc} stderr:\n{merr}"
    )


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_measured_non_collision_stays_a_non_collision(layer, state_root, tmp_path):
    """`between` contains no verb token, so it is evidence of nothing."""
    assert "tee" not in NON_COLLIDING_WORD, (
        f"{NON_COLLIDING_WORD!r} was recorded as containing no `tee`; if that "
        "is now false the record is wrong, not the hook."
    )
    cmd = f"grep -c {NON_COLLIDING_WORD} {layer.path(state_root)}"
    for hook, who in (
        (HOOK, "the live hook"),
        (_unanchored_mutant(tmp_path, layer), "the unanchored mutant"),
    ):
        rc, err = _run(hook, cmd, state_root)
        assert layer.label not in refusal_labels(err), (
            f"{layer.name}: {who} refused {NON_COLLIDING_WORD!r}, which "
            f"contains no verb token at all. rc={rc}\n{err}"
        )


# ── anchoring must NOT narrow the reach: that is worse than the over-block ──
# Anchoring naively on both sides stops matching the forms real invocations
# actually take, silently opening a write route into the protected namespace.
# Every shape below reaches the namespace with NO redirection operator, so
# branch 1 is blind to it and branch 2 is the only thing in the way.
ANCHORED_STILL_REFUSED = [
    ("version-suffixed-python3", "python3 -c pass {p}"),
    ("version-suffixed-python3-dotted", "python3.12 -c pass {p}"),
    ("version-suffixed-perl5", "perl5.36 -e 1 {p}"),
    ("version-suffixed-ruby3", "ruby3.2 -e 1 {p}"),
    ("version-suffixed-node20", "node20 -e 1 {p}"),
    ("alias-nodejs", "nodejs -e 1 {p}"),
    ("alias-ipython", "ipython -c pass {p}"),
    ("alias-gawk", "gawk BEGIN{{}} {p}"),
    ("alias-mawk", "mawk BEGIN{{}} {p}"),
    ("alias-cpio", "cpio -i -F {p}"),
    ("leading-abs-path", "/usr/bin/touch {p}"),
    ("leading-abs-path-interpreter", "/usr/local/bin/python3 -c pass {p}"),
    ("leading-rel-path", "./bin/node -e 1 {p}"),
    ("leading-dotdot-path", "../vendor/perl -e 1 {p}"),
    ("head-first-word", "touch {p}"),
    ("head-after-pipe", "printf x | tee {p}"),
    ("head-after-semicolon", "cd /tmp ; touch {p}"),
    ("head-after-semicolon-nospace", "cd /tmp;touch {p}"),
    ("head-after-and", "cd /tmp && touch {p}"),
    ("head-after-or", "false || touch {p}"),
    ("head-after-subshell", "(touch {p})"),
    ("head-after-cmdsubst", "echo $(touch {p})"),
]


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize(
    "case,tmpl", ANCHORED_STILL_REFUSED, ids=[c for c, _ in ANCHORED_STILL_REFUSED]
)
def test_anchoring_did_not_narrow_the_reach(layer, case, tmpl, state_root):
    cmd = tmpl.format(p=layer.path(state_root))
    assert ">" not in cmd, f"probe for {case} leaked a redirection operator"
    rc, err = run_hook(cmd, state_root)
    assert layer.label in refusal_labels(err), (
        f"{layer.name} layer (hook line {layer.lineno}) did NOT refuse "
        f"{case}: {cmd}\nThe anchoring is too strict and has opened a write "
        f"route into the protected namespace. rc={rc} "
        f"labels={sorted(refusal_labels(err))}\n{err}"
    )
    assert rc == BLOCK


# ════════════════════════════════════════════════════════════════════════════
# The four ways the ONE shared predicate can go wrong: copied, mis-documented,
# unbound, or mis-bounded. Each block below pins one. Every negative result
# here carries a positive control.
# ════════════════════════════════════════════════════════════════════════════

def _hook_grep(pattern, text):
    """Every match, line by line, with the matcher the rules use (Python `re`)."""
    rx = re.compile(pattern)
    return [m.group(0) for line in text.split("\n") for m in rx.finditer(line) if m.group(0)]


def _rebind_verbs(alt):
    """The rules source with the shared verb alternation replaced by `(alt)`, before anything reads it."""
    marker = "ARTIFACT_NS_CAPTURE_RE = "
    assert HOOK_SRC.count(marker) == 1, "the definition after the verb alternation moved"
    return HOOK_SRC.replace(marker, "%s = %r\n%s" % (VERB_VAR, "(%s)" % alt, marker), 1)


def _predicate_doc():
    """The flowed docstring of the one predicate both layers evaluate."""
    return re.sub(r"\s+", " ", bash_safety_rules.writes_namespace.__doc__ or "")


# ── Symptom A: the shared alternation is defined ONCE, and provably so ──────
def test_verb_alternation_is_defined_exactly_once():
    """A second copy anywhere is the drift the one definition exists to prevent."""
    first = _split_alternation(VERB_ALT)[0]
    occurrences = HOOK_SRC.count(first)
    assert occurrences == 1, (
        f"the first write-verb token {first!r} appears {occurrences} times in {RULES}; the "
        f"alternation must be defined exactly ONCE (line {VERB_ALT_LINENO})."
    )


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_both_layers_reference_the_one_shared_verb_definition(layer):
    body = HOOK_SRC[HOOK_SRC.index("def writes_namespace("):]
    body = body[:body.index("\ndef ", 1)]
    assert VERB_VAR in body, f"writes_namespace does not reference {VERB_VAR}"
    assert "\\btee" not in body and "\\bruby" not in body, (
        f"writes_namespace spells verb tokens inline again instead of referencing {VERB_VAR}"
    )


def test_the_two_layer_conditions_are_textually_identical():
    """The strongest divergence pin: both layers evaluate ONE predicate, each on its own namespace."""
    calls = _layer_calls()
    assert len(calls) == 2 and len(set(calls)) == 2, (
        "commit_artifact_rules no longer hands exactly the two namespaces to the one predicate "
        f"writes_namespace: {calls!r}"
    )


# ── Symptom D, mechanism 1: the alternation no longer self-matches ──────────
def test_self_match_probe_is_zero_on_the_bound_predicate():
    """AC2, with the positive control that proves the probe can return a hit.

    Fed its own pattern text with the namespace ABSENT, the bare alternation
    matches twice: in the literal pattern text the character before `python`
    and before `awk` is the `?` of an optional group -- a non-word character --
    so the leading `\\b` holds, the optional prefix matches zero characters,
    and the following `(` satisfies the trailing non-letter class. The verb set
    must NOT be narrowed to fix that (narrowing reopens a write route); binding
    the verb to the namespace is what fixes it, and the bound form -- which is
    what both layers actually evaluate -- matches ZERO times.
    """
    bare = _hook_grep(VERB_ALT, "(%s)" % VERB_ALT)
    assert len(bare) == 2 and all("(" in h for h in bare), (
        "the self-match positive control no longer reproduces: the bare "
        f"alternation matched {bare!r} against its own text, expected exactly "
        "two hits each ending at an open paren. Without this control the zero "
        "below would prove nothing."
    )
    for ctrl in ("tee", "cp", "node"):
        assert not any(ctrl in h for h in bare), (
            f"{ctrl!r} now self-matches; it is a recorded NEGATIVE control "
            "(the character before it in the pattern text is the `b` of `\\b`, "
            "a word character, so no boundary exists). The token shape changed."
        )
    for layer in LAYERS:
        assert BOUND_BRANCH2 in HOOK_SRC, "branch 2 no longer binds the verb to the namespace"
        # The alternation MUST be parenthesised before `.*` is appended:
        # without the group, `.*<namespace>` binds to the LAST alternative
        # only and every other verb stays unbound. That is how the hook
        # composes it (ARTIFACT_WRITE_VERB_RE carries its own outer parens)
        # and getting it wrong here silently weakens the probe.
        bound = "(%s).*%s" % (VERB_ALT, re.escape(os.path.join(
            DEFAULT_STATE_ROOT, layer.prefix)))
        hits = _hook_grep(bound, "(%s)" % VERB_ALT)
        assert hits == [], (
            f"{layer.name}: the BOUND predicate self-matched {hits!r}. Branch 2 "
            "stopped requiring the namespace, so the layer is back to refusing "
            "commands that merely quote its own verb list."
        )


# ── Symptom D, mechanism 2: mere co-occurrence must not refuse ──────────────
def _unbound_branch2_mutant(tmp_path, layer):
    """A throwaway copy with branch 2's namespace binding removed."""
    assert BOUND_BRANCH2 in HOOK_SRC, (
        f"{layer.name}: could not locate branch 2's bound pattern to unbind; "
        f"looked for {BOUND_BRANCH2!r}. Re-derive before trusting the control."
    )
    src = HOOK_SRC.replace(BOUND_BRANCH2, "grep(ARTIFACT_WRITE_VERB_RE, one)", 1)
    assert src != HOOK_SRC, "unbinding mutation was a no-op"
    return _write_mutant(tmp_path, f"unbound-{layer.name}", src)


CO_OCCURRENCE_READS = [
    ("version-suffixed-interpreter", "ls -1 {p} 2>/dev/null | python3 -c 'import sys; print(len(sys.stdin.read()))'"),
    ("dotted-interpreter", "cat {p} 2>/dev/null | python3.12 -m json.tool"),
    ("awk-positional-field", "ls -l {p} | awk '{{print $1}}'"),
]


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize(
    "case,tmpl", CO_OCCURRENCE_READS, ids=[c for c, _ in CO_OCCURRENCE_READS]
)
def test_verb_co_occurrence_alone_does_not_refuse(
    layer, case, tmpl, state_root, tmp_path
):
    """A read that MENTIONS an enumerated verb for an unrelated reason."""
    cmd = tmpl.format(p=layer.path(state_root))
    rc, err = run_hook(cmd, state_root)
    assert layer.label not in refusal_labels(err) and rc == ALLOW, (
        f"{layer.name} layer (hook line {layer.lineno}) refused a READ whose "
        f"only sin is naming an enumerated verb downstream of a pipe: {cmd}\n"
        f"Branch 2 stopped binding its verbs to the namespace. rc={rc}\n{err}"
    )
    # Positive control: unbind branch 2 on a throwaway copy and the SAME probe
    # is refused, so the permit above is load-bearing.
    mrc, merr = _run(_unbound_branch2_mutant(tmp_path, layer), cmd, state_root)
    assert layer.label in refusal_labels(merr), (
        f"{layer.name}: unbinding branch 2 did NOT reproduce the "
        f"co-occurrence over-block for {case}, so this permit proves nothing. "
        f"Re-derive the mutation before trusting it. rc={mrc}\n{merr}"
    )


# ── Symptom B: the namespace written THROUGH a shell variable ───────────────
INDIRECT_WRITES = [
    # The exact shape the old unbound predicate caught (via the bare `>`) and
    # binding alone let through. It is a genuine write into the namespace.
    ("capture-then-redirect", "NS={p}; echo x > \"$NS\""),
    ("capture-then-redirect-braced", "NS={p}; printf x > ${{NS}}"),
    ("export-then-append", "export NS={p}; echo x >> $NS"),
    ("capture-then-verb-argument", "NS={p}; cp /etc/hostname \"$NS\""),
    ("prefix-assignment-into-interpreter-env", "NS={p} python3 -c 'import os; open(os.environ[\"NS\"],\"w\")'"),
]


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize(
    "case,tmpl", INDIRECT_WRITES, ids=[c for c, _ in INDIRECT_WRITES]
)
def test_write_through_a_shell_variable_is_refused(layer, case, tmpl, state_root):
    cmd = tmpl.format(p=layer.path(state_root))
    rc, err = run_hook(cmd, state_root)
    assert layer.label in refusal_labels(err), (
        f"{layer.name} layer (hook line {layer.lineno}) did NOT refuse {case}, "
        f"a write into its namespace through a shell variable: {cmd}\n"
        f"rc={rc} labels={sorted(refusal_labels(err))}\n{err}"
    )
    assert rc == BLOCK


# ── writes whose separators sit INSIDE quotes, or on another line ───────────
SEPARATOR_EVADING_WRITES = [
    ("semicolon-inside-interpreter-program", "python3 -c 'import os; open(\"{p}\",\"w\")'"),
    ("heredoc-body-on-a-later-line", "python3 - <<'EOF'\nopen(\"{p}\",\"w\")\nEOF"),
    ("redirect-inside-awk-program", "awk 'BEGIN{{printf \"\" > \"{p}\"}}'"),
]


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize(
    "case,tmpl", SEPARATOR_EVADING_WRITES,
    ids=[c for c, _ in SEPARATOR_EVADING_WRITES],
)
def test_separator_evading_writes_are_refused(layer, case, tmpl, state_root):
    """Binding must not be defeated by a quoted `;` or by a newline.

    `grep` is line-based and `.` does not match a newline, so the ordered
    binding is evaluated on a single-line view of the command. Without it the
    heredoc case below writes the namespace with the verb on another line.
    """
    cmd = tmpl.format(p=layer.path(state_root))
    rc, err = run_hook(cmd, state_root)
    assert layer.label in refusal_labels(err), (
        f"{layer.name} layer (hook line {layer.lineno}) did NOT refuse {case}: "
        f"{cmd!r}\nrc={rc} labels={sorted(refusal_labels(err))}\n{err}"
    )
    assert rc == BLOCK


# ── Symptoms B and C: the comments must not re-assert what was measured false
def test_symptom_b_difference_three_is_stated_as_a_relaxation():
    """The predicate's own account names its limits and the barrier that covers them."""
    doc = _predicate_doc()
    assert "Positional, not semantic" in doc
    assert "Residual under-block" in doc, "the writes the predicate misses are no longer named"
    assert "pretool-git-privilege-guard.py" in doc, (
        "the structural barrier that covers the residual is no longer named beside it."
    )


def test_symptom_c_read_only_claim_stays_qualified():
    doc = _predicate_doc()
    assert "Residual over-block" in doc, (
        "the reads the predicate still refuses are no longer named, so 'permitted' is unqualified again."
    )


# ── T1-1: a directory named like an interpreter is not an interpreter launch ─
# Measured on the base: with the state root under a directory named
# `rerun-node20-files`, `python3-x`, or a home directory named node, a pure read
# through a captured variable (`NS=<ns>; ls -l "$NS"`) was refused on BOTH
# layers, for the main agent and a subagent: the namespace path itself carried
# `node`/`python` as a path segment, the verb's old one-character right bound
# accepted the `/` after it, and branch 3 (a verb, then a `$` expansion) fired.
# The same read under `rerun-n20-files` was permitted. Each read below carries
# a positive control: the old right bound, restored on a throwaway copy,
# refuses it again, so the permit is the fix and not a probe that never hits.
INTERPRETER_NAMED_ROOTS = [
    ("node20-dir", ("rerun-node20-files", "state")),
    ("python3-x-dir", ("python3-x", "state")),
    ("node-home", ("home", "node", ".claude", "state")),
]
PAYLOAD_KINDS = [
    ("main-agent", {}),
    ("subagent", {"agent_id": "a0b1c2d3", "agent_type": "general-purpose"}),
]

T1_1_READS = [
    ("variable-captured-then-listed", 'NS={p}; ls -l "$NS"'),
    ("variable-captured-then-listed-quiet", 'NS={p}; ls -l "$NS" 2>/dev/null'),
    ("variable-captured-then-read-piped-to-python",
     "NS={p}; cat \"$NS\" | python3 -c 'import sys; print(len(sys.stdin.read()))'"),
]

# Writes under the same interpreter-named roots: every one stays refused by the
# layer under test. Several are interpreter launches; one launches the
# interpreter FROM the interpreter-named state root (`<root>/bin/python3`), so
# the word's last path segment is the verb and an earlier segment is a
# directory named like one; three split the verb's word through an expansion
# or a brace list, which the right bound must read as the end of the word.
T1_1_WRITES = [
    ("capture-then-redirect", 'NS={p}; echo x > "$NS"'),
    ("redirect", "echo x > {p}"),
    ("python-program-writes", "python3 -c 'open(\"{p}\",\"w\")'"),
    ("python-env-prefix-writes",
     "NS={p} python3 -c 'import os; open(os.environ[\"NS\"],\"w\")'"),
    ("perl-writes-through-variable",
     "NS={p}; perl -e 'open F, \">\", $ARGV[0]' \"$NS\""),
    ("ruby-writes", "ruby -e 'File.write(ARGV[0], \"\")' {p}"),
    ("node20-writes",
     "node20 -e 'require(\"fs\").writeFileSync(process.argv[1], \"\")' {p}"),
    ("python-from-interpreter-named-dir", "{d}/bin/python3 -c 'open(\"{p}\",\"w\")'"),
    ("python-debug-binary", "python3-dbg -c 'open(\"{p}\",\"w\")'"),
    ("tee", "printf x | tee {p}"),
    ("capture-then-copy", 'NS={p}; cp /etc/hostname "$NS"'),
    ("tee-split-by-ifs", "printf x | tee${{IFS}}{p}"),
    ("tee-split-by-brace-list", "printf x | {{tee,{p}}}"),
    ("copy-split-by-ifs", "cp${{IFS}}/etc/hostname${{IFS}}{p}"),
]


@pytest.fixture(
    scope="module",
    params=INTERPRETER_NAMED_ROOTS,
    ids=[n for n, _ in INTERPRETER_NAMED_ROOTS],
)
def interpreter_named_root(request, tmp_path_factory):
    """(state_root, home) with an interpreter-named directory in the state root."""
    name, parts = request.param
    base = tmp_path_factory.mktemp("t1-1-" + name)
    root = os.path.join(str(base), *parts)
    os.makedirs(root)
    resolved = harness_state_dir(root)
    assert resolved == root, (
        f"the production state-dir library did not honour CLAUDE_STATE_DIR: "
        f"asked for {root}, got {resolved}"
    )
    home = (
        os.path.join(str(base), "home", "node")
        if name == "node-home"
        else os.path.join(str(base), "home")
    )
    os.makedirs(home, exist_ok=True)
    return resolved, home


def _run_payload(hook, command, state_root, home, extra):
    """Drive a hook copy with a main-agent or subagent payload and a scratch HOME."""
    env = os.environ.copy()
    env["CLAUDE_STATE_DIR"] = state_root
    env["HOME"] = home
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "session_id": "t1-1-session"}
    payload.update(extra)
    proc = subprocess.run(
        ["bash", hook], input=json.dumps(payload), env=env,
        text=True, capture_output=True,
    )
    return proc.returncode, proc.stderr


def _old_right_bound_mutant(tmp_path):
    """A throwaway hook copy whose verbs carry the pre-T1-1 right bound."""
    assert BOUNDARY_SUFFIX in VERB_ALT, (
        "could not locate the shared verb definition's right bound; "
        f"parsed {VERB_ALT!r} at line {VERB_ALT_LINENO}"
    )
    src = _rebind_verbs(VERB_ALT.replace(BOUNDARY_SUFFIX, OLD_BOUNDARY_SUFFIX))
    return _write_mutant(tmp_path, "old-right-bound", src)


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize("kind,extra", PAYLOAD_KINDS, ids=[k for k, _ in PAYLOAD_KINDS])
@pytest.mark.parametrize("shape,tmpl", T1_1_READS, ids=[s for s, _ in T1_1_READS])
def test_read_under_interpreter_named_directory_is_permitted(
    layer, kind, extra, shape, tmpl, interpreter_named_root, tmp_path
):
    state, home = interpreter_named_root
    cmd = tmpl.format(p=layer.path(state))
    rc, err = _run_payload(HOOK, cmd, state, home, extra)
    assert layer.label not in refusal_labels(err), (
        f"{layer.name} layer (hook line {layer.lineno}) refused a {kind} READ "
        f"because a directory in the state root is named like an interpreter: "
        f"{cmd}\nstderr:\n{err}"
    )
    assert rc == ALLOW, (
        f"{kind} read probe was refused by another layer: {cmd}\n"
        f"labels={sorted(refusal_labels(err))} rc={rc}\n{err}"
    )
    # Positive control: the old right bound refuses the same read, so the
    # permit above is the fix and not a probe that can never hit.
    mrc, merr = _run_payload(_old_right_bound_mutant(tmp_path), cmd, state, home, extra)
    assert layer.label in refusal_labels(merr), (
        f"{layer.name}: the pre-T1-1 right bound did NOT refuse {cmd}, so "
        f"this permit proves nothing. rc={mrc}\n{merr}"
    )


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
@pytest.mark.parametrize("kind,extra", PAYLOAD_KINDS, ids=[k for k, _ in PAYLOAD_KINDS])
@pytest.mark.parametrize("shape,tmpl", T1_1_WRITES, ids=[s for s, _ in T1_1_WRITES])
def test_write_under_interpreter_named_directory_is_refused(
    layer, kind, extra, shape, tmpl, interpreter_named_root
):
    state, home = interpreter_named_root
    cmd = tmpl.format(p=layer.path(state), d=state)
    rc, err = _run_payload(HOOK, cmd, state, home, extra)
    labels = refusal_labels(err)
    assert layer.label in labels, (
        f"{layer.name} layer (hook line {layer.lineno}) did NOT refuse a {kind} "
        f"write into its namespace under an interpreter-named directory: {cmd}\n"
        f"rc={rc} labels={sorted(labels)}\n{err}"
    )
    assert rc == BLOCK


def test_last_path_segment_verb_is_still_a_verb_and_directory_is_not():
    """The right bound, measured directly with the hook's own grep and alternation."""
    verb = "(%s)" % VERB_ALT
    for word in ("/usr/bin/python3 -c", "\"/usr/bin/python3\" -c", "python3-dbg -c",
                 "perl5.36 -e", "node20 -e", "tee${IFS}x", "{tee,x}", "nodejs"):
        assert _hook_grep(verb, word), f"{word!r} is a launch and must match a verb"
    for word in ("/tmp/rerun-node20-files/x", "/tmp/python3-x/x", "/".join(("", "home", "node", "x")),
                 "/tmp/perl5/x", "/opt/tee/x", "nodes", "untouched"):
        assert not _hook_grep(verb, word), f"{word!r} is no launch and must not match"


# ── AC8 / hygiene: the hook still parses and still permits benign work ──────
def test_zz_no_artifact_was_ever_written(state_root):
    """The hook inspects command strings; it must never have created anything."""
    for root in (state_root, DEFAULT_STATE_ROOT):
        for lyr in LAYERS:
            leaked = glob.glob(os.path.join(root, f"{lyr.prefix}sid-nonce.json"))
            assert not leaked, f"probe created a real artifact: {leaked}"


def test_zz_hook_still_parses():
    proc = subprocess.run(
        ["bash", "-n", HOOK], text=True, capture_output=True
    )
    assert proc.returncode == 0, f"hook no longer parses:\n{proc.stderr}"


@pytest.mark.parametrize(
    "cmd", ["echo hello", "git status --short", "ls -1 /tmp", "pwd"]
)
def test_zz_ordinary_benign_command_is_permitted(cmd, state_root):
    rc, err = run_hook(cmd, state_root)
    assert rc == ALLOW, f"benign command refused: {cmd}\nrc={rc}\n{err}"
    assert refusal_labels(err) == set()


# location-rules U9, U10: a grant, attestation or user-intent file is refused for what it is, wherever the command's
# spelling puts it: a `cd` into the state directory, a link to it, or $TMPDIR when the state directory lies below it.
def _run_at(command, state, cwd, tmpdir):
    env = {k: v for k, v in os.environ.items() if k not in ("TMPDIR", "TMP", "TEMP", "TEMPDIR", "CLAUDE_TMPDIR")}
    env.update(CLAUDE_STATE_DIR=state, TMPDIR=tmpdir)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    return subprocess.run(["bash", HOOK], input=payload, env=env, text=True, capture_output=True).returncode


def test_namespace_write_one_verdict_at_every_spelling(tmp_path):
    tmpdir = tmp_path / "t"
    (tmpdir / "st").mkdir(parents=True)
    state = harness_state_dir(str(tmpdir / "st"))
    os.makedirs(state, exist_ok=True)
    link = tmp_path / "sl"
    link.symlink_to(state)
    rel = os.path.relpath(state, tmpdir)
    work = tmp_path / "w"
    work.mkdir()
    passed = [command for name in (GRANT_PREFIX + "x.json", ATTEST_PREFIX + "x.json", "claude-commit-userintent-x.flag")
              for command in (f"touch {state}/{name}", f"cd {state} && touch {name}", f"touch {link}/{name}",
                              f'touch "$TMPDIR/{rel}/{name}"',
                              f"echo x > {state}/../{os.path.basename(state)}/{name}")
              if _run_at(command, state, str(work), str(tmpdir)) != BLOCK]
    assert passed == [], passed
    for command in (f"touch {work}/{GRANT_PREFIX}x.json", f"cd {state} && cat {GRANT_PREFIX}x.json",
                    f'touch "$TMPDIR/{GRANT_PREFIX}x.json"'):
        assert _run_at(command, state, str(work), str(tmpdir)) == ALLOW, command
