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
of the hook was previously hand-mirrored with nothing binding the copies):

  * the attestation filename prefix comes from the named production constant
    `hooks/lib/commit_pipeline.py::ATTEST_PREFIX`, which the hook's own
    comment declares to be its source;
  * the grant filename prefix is AST-extracted from the canonical minter
    `scripts/write-commit-grant.py`, at the statement that composes the grant
    path — production's own source of truth for that filename;
  * the state ROOT comes from running the production shell library
    `hooks/lib/harness_state_dir.sh::harness_state_dir`, the same function the
    hook itself calls.

`test_hook_prefix_literal_matches_production_*` then asserts the hook's own
shell literal equals the Python-derived prefix. That is the drift tie: rename
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

from commit_pipeline import ATTEST_PREFIX  # noqa: E402

with open(HOOK) as _fp:
    HOOK_SRC = _fp.read()
HOOK_LINES = HOOK_SRC.splitlines()

BLOCK = 2
ALLOW = 0

# The shell variables the hook uses for the two namespaces. These are variable
# NAMES, not namespace values -- the values are derived below.
ATTEST_VAR = "COMMIT_DISPATCH_ATTEST_RE"
GRANT_VAR = "COMMIT_GRANT_RE"

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
    yielding the historical default root.
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


# ── derivation 3: the hook's own shell literal, for the drift tie ───────────
def _hook_prefix_literal(var):
    """Extract the filename prefix the hook appends to the state root for `var`."""
    pat = re.compile(
        r"^" + re.escape(var) + r"=.*?%/\}/(?P<prefix>[^\"]+)\"",
    )
    for lineno, line in enumerate(HOOK_LINES, start=1):
        m = pat.search(line)
        if m:
            return m.group("prefix"), lineno
    raise AssertionError(
        f"no `{var}=` assignment composing a prefix onto the state root was "
        f"found in {HOOK}. The layer was restructured; re-point this "
        "derivation rather than hardcoding a prefix."
    )


# ── derivation 4: the SHARED verb alternation, from its ONE definition ──────
# Until 2026-10-08 each layer carried its OWN inline copy of this alternation,
# and this derivation parsed the copy out of the layer's own `if` block. That
# shape was itself the defect: the two copies had ALREADY drifted (identical
# 16-token sets, `\bi?python([^A-Za-z_]|$)` 7th in Layer 1.E3 and 12th in Layer
# 1.E4), so a per-layer parse could only ever report what each copy happened to
# say and could NEVER report that the two disagreed. The alternation is now
# hoisted into one shell variable; this derivation reads THAT, and the two
# `test_*shared_verb_definition*` / `*defined_exactly_once` tests below assert
# both layers reference it and no second copy has reappeared.
VERB_VAR = "ARTIFACT_WRITE_VERB_RE"


def _hoisted_verb_alternation():
    """(lineno, alternation) of the single shared write-verb definition."""
    pat = re.compile(r"^" + re.escape(VERB_VAR) + r"='\((?P<alt>.+)\)'$")
    for lineno, line in enumerate(HOOK_LINES, start=1):
        m = pat.match(line)
        if m:
            return lineno, m.group("alt")
    raise AssertionError(
        f"no single-quoted `{VERB_VAR}='(...)'` definition was found in {HOOK}. "
        "The shared write-verb alternation was renamed, split, or inlined back "
        "into the layers. Re-point this derivation at its new single source of "
        "truth. Do NOT restate the token list here, and do NOT go back to "
        "parsing a per-layer copy -- that is the shape that let the two copies "
        "drift apart in the first place."
    )


VERB_ALT_LINENO, VERB_ALT = _hoisted_verb_alternation()


def _layer_condition(var):
    """The full `if` condition text of a layer, as a list of source lines."""
    guard = 'grep -qE "${%s}"' % var
    for idx, line in enumerate(HOOK_LINES):
        if guard in line and line.lstrip().startswith("if "):
            out = []
            for cur in HOOK_LINES[idx:idx + 12]:
                out.append(cur)
                if cur.rstrip().endswith("; then"):
                    return idx + 1, out
            raise AssertionError(
                f"layer {var} at line {idx + 1}: no `; then` terminator within "
                "12 lines; the condition was restructured."
            )
    raise AssertionError(f"no layer guarded by ${{{var}}} found in {HOOK}")


def _layer_branches(var):
    """Return (lineno, redirection_branch_text, branch2_alternation) for a layer."""
    guard = 'grep -qE "${%s}"' % var
    for idx, line in enumerate(HOOK_LINES):
        if guard in line and line.lstrip().startswith("if "):
            block = "\n".join(HOOK_LINES[idx : idx + 7])
            assert "${%s}" % VERB_VAR in block, (
                f"layer {var} at line {idx + 1} does not reference the shared "
                f"verb definition ${{{VERB_VAR}}}. Either it grew a private "
                "copy of the alternation again -- the exact drift this hoist "
                "exists to prevent -- or the reference was renamed."
            )
            redirect = None
            # The first occurrence is the bare namespace guard; the redirection
            # branch is the one whose pattern has operator syntax ahead of the
            # variable reference. The pattern may itself contain a backslash-
            # escaped double quote (the optional quote-character class), so the
            # scanner must step over `\"` rather than stop at it.
            for cand in re.finditer(r'grep -qE "(?P<pat>(?:[^"\\]|\\.)*)"', block):
                pat = cand.group("pat")
                if pat.endswith("${%s}" % var) and pat != "${%s}" % var:
                    redirect = pat
                    break
            return idx + 1, redirect, VERB_ALT
    raise AssertionError(f"no layer guarded by ${{{var}}} found in {HOOK}")


# Branch 2's verbs are ANCHORED -- `\bVERB([^A-Za-z_]|$)`, some carrying an
# optional real-binary-alias group (`cp(io)?`, `i?python`, `[gmn]?awk`,
# `node(js)?`). That shape puts a `|` INSIDE a group, so the alternation can
# only be split at paren depth 0: a flat `alt.split("|")` shreds every token
# into fragments like `$)` and `tee([^A-Za-z_]`. This parser previously assumed
# the FLAT, UNANCHORED token shape and is upgraded here, not relaxed -- the
# polarity assertions it feeds are unchanged.
BOUNDARY_SUFFIX = "([^A-Za-z_]|$)"
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
    _, _, alt = _layer_branches(var)
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
        self.lineno, self.redirect_branch, _ = _layer_branches(var)
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
    # ── the WIDER half of the same over-block, measured 2026-10-08 ──────────
    # Branch 2 used to match a verb ANYWHERE in the command, so the real
    # trigger was "names the namespace AND mentions any enumerated interpreter
    # or destination-as-argument verb anywhere, for ANY reason" -- not "hands
    # that verb the namespace". Every shape below is fully read-only and was
    # REFUSED under the layer's own label on both layers. The natural auditing
    # shape is the first two: list the namespace, parse the JSON with a
    # one-liner.
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
def test_hook_prefix_literal_matches_production_attest_constant():
    literal, lineno = _hook_prefix_literal(ATTEST_VAR)
    assert literal == ATTEST_PREFIX, (
        f"{HOOK}:{lineno} composes a different attestation prefix than the "
        f"production constant commit_pipeline.ATTEST_PREFIX. The two copies "
        f"have drifted: hook={literal!r} constant={ATTEST_PREFIX!r}. Every "
        "probe in this file would otherwise have silently re-targeted itself."
    )


def test_hook_prefix_literal_matches_production_grant_minter():
    literal, lineno = _hook_prefix_literal(GRANT_VAR)
    assert literal == GRANT_PREFIX, (
        f"{HOOK}:{lineno} composes a different grant prefix than the "
        f"canonical minter {GRANT_MINTER} writes: hook={literal!r} "
        f"minter={GRANT_PREFIX!r}. A hand-authored grant at the minter's "
        "filename would no longer be refused by this layer."
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
    assert layer.redirect_branch.endswith("${%s}" % layer.var)
    operator_part = layer.redirect_branch[: -len("${%s}" % layer.var)]
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

    default_path = layer.path(DEFAULT_STATE_ROOT)
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
    bound = 'grep -qE "%s"' % layer.redirect_branch.replace("\\", "\\")
    assert bound in HOOK_SRC, (
        f"{layer.name}: could not locate branch 1's text to revert; "
        f"parsed pattern was {layer.redirect_branch!r}"
    )
    reverted_src = HOOK_SRC.replace(bound, 'grep -qE ">"', 1)
    assert reverted_src != HOOK_SRC, "mutation was a no-op"

    mutant = tmp_path / "reverted-hook.sh"
    mutant.write_text(reverted_src)
    # The hook resolves its libraries relative to its OWN location and falls
    # back to the default state root when it cannot source them. Without this
    # symlink the mutant would silently ignore CLAUDE_STATE_DIR, aim at the
    # real namespace, and permit the sandbox probe for the wrong reason.
    lib_link = tmp_path / "lib"
    if not lib_link.exists():
        lib_link.symlink_to(os.path.join(HOOKS_DIR, "lib"))

    probe = f"ls -la {layer.path(state_root)} 2>/dev/null"
    env = os.environ.copy()
    env["CLAUDE_STATE_DIR"] = state_root
    proc = subprocess.run(
        ["bash", str(mutant)],
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
    anchored = "%s='(%s)'" % (VERB_VAR, VERB_ALT)
    assert anchored in HOOK_SRC, (
        f"{layer.name}: could not locate the shared verb definition to "
        f"de-anchor; parsed {VERB_ALT!r} at line {VERB_ALT_LINENO}"
    )
    src = HOOK_SRC.replace(
        anchored, "%s='(%s)'" % (VERB_VAR, _deanchored(VERB_ALT)), 1
    )
    assert src != HOOK_SRC, "de-anchoring mutation was a no-op"
    mutant = tmp_path / f"unanchored-{layer.name}-hook.sh"
    mutant.write_text(src)
    # The hook resolves its libraries relative to its OWN location and falls
    # back to the default state root when it cannot source them. Without this
    # symlink the mutant would ignore CLAUDE_STATE_DIR and aim at the real
    # namespace, permitting the probe for the wrong reason.
    lib_link = tmp_path / "lib"
    if not lib_link.exists():
        lib_link.symlink_to(os.path.join(HOOKS_DIR, "lib"))
    return str(mutant)


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
# 2026-10-08 — the four symptoms of the ONE un-hoisted / mis-documented /
# mis-bound shared predicate. Each block below pins one so it cannot silently
# return. Every negative result here carries a positive control.
# ════════════════════════════════════════════════════════════════════════════

def _hook_grep(pattern, text):
    """Match with the SAME grep the hook resolves at runtime.

    Deliberately NOT a hardcoded path and NOT Python's `re`: the hook calls a
    bare `grep` from a non-interactive bash, so resolving it the same way is
    the only measurement that describes production. (An interactive shell here
    may alias `grep` to an ignore-file-applying wrapper, which is a different
    program and would measure the wrong thing.)
    """
    proc = subprocess.run(
        ["bash", "-c", 'grep -oE "$1" || true', "_", pattern],
        input=text,
        text=True,
        capture_output=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def _write_mutant(tmp_path, name, src):
    """Materialise a throwaway hook copy that can still find its libraries."""
    mutant = tmp_path / name
    mutant.write_text(src)
    lib_link = tmp_path / "lib"
    if not lib_link.exists():
        lib_link.symlink_to(os.path.join(HOOKS_DIR, "lib"))
    return str(mutant)


def _comment_region(marker, var):
    """(lineno, flowed_text) of the comment block from `marker` to the `if`.

    The text is FLOWED -- comment markers stripped and whitespace collapsed --
    so an assertion about a sentence is not defeated by where the sentence
    happens to wrap. Asserting on raw lines would make every phrase check a
    hostage to line width.
    """
    start = next(
        (i for i, line in enumerate(HOOK_LINES) if line.startswith(marker)), None
    )
    assert start is not None, f"no comment block starting {marker!r} in {HOOK}"
    guard = 'grep -qE "${%s}"' % var
    for end in range(start, len(HOOK_LINES)):
        if guard in HOOK_LINES[end] and HOOK_LINES[end].lstrip().startswith("if "):
            body = " ".join(
                re.sub(r"^#\s?", "", line) for line in HOOK_LINES[start:end]
            )
            return start + 1, re.sub(r"\s+", " ", body)
    raise AssertionError(f"no `if` guarded by ${{{var}}} after {marker!r}")


# ── Symptom A: the shared alternation is defined ONCE, and provably so ──────
def test_verb_alternation_is_defined_exactly_once():
    """A second copy anywhere is the drift this hoist exists to prevent."""
    literal = "(%s)" % VERB_ALT
    occurrences = HOOK_SRC.count(literal)
    assert occurrences == 1, (
        f"the write-verb alternation appears {occurrences} times in {HOOK}; it "
        f"must appear exactly ONCE (the definition at line {VERB_ALT_LINENO}). "
        "Two copies is precisely the state that drifted: identical 16-token "
        "sets in a different order, each block telling maintainers to anchor "
        "any verb they add, and nothing detecting the disagreement."
    )


@pytest.mark.parametrize("layer", LAYERS, ids=LAYER_IDS)
def test_both_layers_reference_the_one_shared_verb_definition(layer):
    lineno, lines = _layer_condition(layer.var)
    text = "\n".join(lines)
    assert "${%s}" % VERB_VAR in text, (
        f"{layer.name} layer (hook line {lineno}) does not reference "
        f"${{{VERB_VAR}}}. It has its own verb list again."
    )
    assert "\\btee" not in text and "\\bruby" not in text, (
        f"{layer.name} layer (hook line {lineno}) spells verb tokens inline "
        f"again instead of referencing ${{{VERB_VAR}}}:\n{text}"
    )


def test_the_two_layer_conditions_are_textually_identical():
    """The strongest divergence pin: same branches, same order, same patterns.

    Normalising away only each layer's own namespace variable, the two
    conditions must be byte-identical. This fails on ANY divergence -- a verb
    reordered, a branch added to one layer only, a gap pattern changed, a
    binding dropped -- not merely on the verb list drifting.
    """
    rendered = {}
    for layer in LAYERS:
        lineno, lines = _layer_condition(layer.var)
        rendered[layer.name] = (
            lineno,
            "\n".join(lines).replace("${%s}" % layer.var, "${__NAMESPACE__}"),
        )
    (n1, (l1, t1)), (n2, (l2, t2)) = rendered.items()
    assert t1 == t2, (
        f"the {n1} layer (hook line {l1}) and the {n2} layer (hook line {l2}) "
        "no longer share one predicate. Normalised for their own namespace "
        f"variable they must be identical.\n--- {n1} ---\n{t1}\n--- {n2} ---\n{t2}"
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
    bound = 'grep -qE "${%s}.*${%s}"' % (VERB_VAR, layer.var)
    assert bound in HOOK_SRC, (
        f"{layer.name}: could not locate branch 2's bound pattern to unbind; "
        f"looked for {bound!r}. Re-derive before trusting the control."
    )
    src = HOOK_SRC.replace(bound, 'grep -qE "${%s}"' % VERB_VAR, 1)
    assert src != HOOK_SRC, "unbinding mutation was a no-op"
    return _write_mutant(tmp_path, f"unbound-{layer.name}-hook.sh", src)


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
    lineno, region = _comment_region("# Layer 1.E3", ATTEST_VAR)
    assert "none of them a relaxation" not in region, (
        f"{HOOK}:{lineno} again asserts its three differences from Layer 1.E2 "
        "include no relaxation. Difference #3 IS one: the predicate went from "
        "(namespace anywhere) AND (write token anywhere) to a BOUND form, "
        "which reduces reach on purpose. Asserting otherwise tells a "
        "maintainer the repair had no cost when it has a named one."
    )
    assert "RELAXATION" in region, (
        f"{HOOK}:{lineno}: the relaxation is no longer labelled as such."
    )
    assert "RESIDUAL" in region, (
        f"{HOOK}:{lineno}: the residual the relaxation leaves is no longer "
        "named. A maintainer must not have to re-measure to find it."
    )
    assert "pretool-git-privilege-guard.py" in region, (
        f"{HOOK}:{lineno}: the structural barrier that actually covers the "
        "residual is no longer named beside it."
    )


def test_symptom_c_read_only_claim_stays_qualified():
    lineno, region = _comment_region("# Layer 1.E4", GRANT_VAR)
    assert "Read-only inspection: permitted, but" not in region, (
        f"{HOOK}:{lineno} restates the unqualified claim. It sat in the "
        "comment block of the very layer that refused a read-only probe: a "
        "fully read-only command naming this namespace and separately "
        "invoking an enumerated interpreter WAS refused here."
    )
    assert "RESIDUAL OVER-BLOCK" in region, (
        f"{HOOK}:{lineno}: the residual over-block that survives the repair is "
        "no longer named, so 'permitted' is unqualified again."
    )
    assert "does not HAND the namespace" in region, (
        f"{HOOK}:{lineno}: the qualification on 'permitted' is gone."
    )


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
