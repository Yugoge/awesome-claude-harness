#!/usr/bin/env python3
"""Two language-agnostic soundness checks that gate a landing, with per-check
HUNK-level failure attribution.

Binding acceptance: docs/dev/specs/spec-20260914-052140.md section 5.3.

    SC-1  the combined post-image must parse / compile for its own kind.
    SC-2  a key call point must smoke-test.

WHAT THIS MODULE IS
-------------------
A pure function of its inputs plus at most one private temporary artifact at a
time, behind a standalone entry point that accepts a candidate image, a HUNK
map and an identity record from ANY producer. It performs no git index
read-modify-write, does no staging, and is fully exercisable with synthetic
inputs. It EMITS a verdict; it never decides a landing, never picks a winner,
never drops or reorders a claimant's work, and never resolves a contested
region. ``gate_pass is True`` is the sole authorization it issues; ``False``
and ``None`` issue none.

A passing check is NOT proof of ownership. A failing check is NOT a report of
a clash with another claimant. The vocabulary below is provably disjoint from
the ownership namespace, and ``gate_vocabulary()`` derives that vocabulary by
introspection so the disjointness test cannot drift from the implementation.

THE WITNESS ADMISSIBILITY RULE (the reason this file exists)
------------------------------------------------------------
For each residual diagnostic key -- a key the candidate produces that the
baseline did not -- the gate searches for a minimal hunk set that REPRODUCES
that key. Two relations are kept apart, because conflating them is the defect
this module was written to remove:

    CAUSING a failure   composing W alone reproduces the key, and no proper
                        subset of W does.

    EXPOSING a failure  removing W from the candidate RESTORES a key the
                        candidate had REPAIRED, i.e. a key in
                        (baseline_keys - candidate_keys).

Exposure is detected by that POSITIVE signature. It is NOT detected by "the
check still fails after W is removed": on a passing baseline nothing was
repaired, so nothing can be exposed, and two claimants who each break one
thing are each named -- which the negative formulation could not do, because
removing either one leaves the other's failure standing. The three scenarios
that pin the rule:

    joint failure, passing baseline    witness is EXACTLY {h1, h2}
    masking, broken baseline           NO hunk is named; the repairing hunk is
                                       recorded separately as an unmasking
                                       witness, never as a cause
    two independent defects, passing   BOTH causes named, one per residual
    baseline                           occurrence

GATE COVERAGE CLAIM (checked against measurement, never asserted)
------------------------------------------------------------------
``GATE_COVERAGE_CLAIM`` below states exactly which landing routes of
``scripts/stage-owned-hunks.py`` this module gates today, and exactly which
present no pre-mutation candidate image for it to gate. It is a claim about a
measurable fact, and the lane's tests re-derive the route inventory from the
stager's own CLI parser and compare it against this string. A route added
later that is not in this claim makes the comparison fail; the claim can never
silently read "every route" while covering fewer.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import weakref

# ---------------------------------------------------------------------------
# Declared fixed policy. The kind -> predicate registry is POLICY; what is
# discovered at run time is the KIND, the entry form, the invocation role, the
# required-anchor set and the structured-data role. No path, heading, symbol
# or diagnostic literal specific to any particular change appears below.
# ---------------------------------------------------------------------------

KIND_PYTHON = "python"
KIND_SHELL = "shell"
KIND_JSON = "json"
KIND_MARKDOWN = "markdown_doc"

EXTENSION_KIND_REGISTRY = {
    ".py": KIND_PYTHON,
    ".sh": KIND_SHELL,
    ".bash": KIND_SHELL,
    ".json": KIND_JSON,
    ".md": KIND_MARKDOWN,
}

INTERPRETER_KIND_REGISTRY = {
    "python": KIND_PYTHON,
    "python2": KIND_PYTHON,
    "python3": KIND_PYTHON,
    "sh": KIND_SHELL,
    "bash": KIND_SHELL,
    "dash": KIND_SHELL,
    "ksh": KIND_SHELL,
    "zsh": KIND_SHELL,
}

CHECK_SC1 = "SC-1"
CHECK_SC2 = "SC-2"
MANDATORY_CHECKS = (CHECK_SC1, CHECK_SC2)

RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_NOT_ASSERTED = "not_asserted"

ROLE_DIRECT_EXECUTION = "direct_execution"
ROLE_MODULE_LOAD = "module_load"
ROLE_DATA = "data"
ROLE_UNKNOWN = "unknown"

JSON_ROLE_SCHEMA = "schema"
JSON_ROLE_INSTANCE = "instance"
JSON_ROLE_UNKNOWN = "unknown"

SMOKE_FORM_CALLER = "existing_caller_invocation"
SMOKE_FORM_HELP = "help_surface"
SMOKE_FORM_DRY_RUN = "dry_run_surface"
SMOKE_FORM_CONSUMER_CONTRACT = "declared_consumer_contract"
SMOKE_FORM_ANCHOR_PRESERVATION = "required_anchor_preservation"

STATE_NOT_RUN = "not_run"
STATE_RAN = "ran"
STATE_UNAVAILABLE = "unavailable"

REASON_NO_DECLARED_PARSER_FOR_KIND = "no_declared_parser_for_kind"
REASON_NO_DECLARED_CONSUMER_CONTRACT = (
    "no_declared_consumer_contract_for_structured_data")
REASON_NO_SIDE_EFFECT_FREE_ENTRY_FORM = (
    "no_side_effect_free_entry_form_discovered")
REASON_CALLER_NOT_EQUIVALENT = (
    "caller_invocation_not_observationally_equivalent")
REASON_ANCHOR_SCHEME_UNDERIVABLE = "anchor_resolution_scheme_underivable"
REASON_KIND_UNDETECTABLE = "kind_undetectable"
REASON_KIND_SIGNAL_DISAGREEMENT = "kind_signal_disagreement"
REASON_REGION_GRANULARITY = "region_granularity_not_hunk_level"
REASON_NO_CANDIDATE_IMAGE = "no_candidate_image_presented"
REASON_UNSUPPORTED_SCHEMA_DIALECT = "unsupported_schema_dialect"
REASON_COMPOSER_SUPPLIED_DIGEST = "composer_supplied_content_sha256"
REASON_UNRESOLVED_EVALUATION = "unresolved_evaluation"
REASON_ALL_ENTRY_FORMS_NOT_RUN = "all_discovered_entry_forms_not_run"
REASON_IDENTITY_MISMATCH = "candidate_identity_mismatch"

# The no-blame sentinels. Three, not two: the third closes the branch in which
# the search terminated under its own bound before any admissible set was
# found. Leaving that branch unnamed is what makes two conforming
# implementations diverge on byte-identical input.
ATTRIBUTION_NO_COMBINATION = "no_hunk_combination_caused_this"
ATTRIBUTION_MASKED_PREEXISTING = "masked_preexisting"
ATTRIBUTION_NO_ADMISSIBLE_WITNESS = "no_admissible_witness_found"

ATTRIBUTION_REASON_NO_RESIDUAL = (
    "failure_present_in_baseline_with_no_residual_diagnostic")
ATTRIBUTION_REASON_EXPOSED = "residual_diagnostic_exposed_not_introduced"
ATTRIBUTION_REASON_SEARCH_BOUNDED_OUT = (
    "witness_search_terminated_under_its_own_bound_before_an_admissible_set")

LOCATION_OUTSIDE_ALL_HUNKS = "outside_all_hunks"
LOCATION_UNAVAILABLE = "location_unavailable"
LOCATION_AT_EOF = "at_eof"

COMPOSE_COMPOSED = "composed"
COMPOSE_NOT_COMPOSABLE = "not_composable"

EVAL_OK = "ok"
EVAL_UNRESOLVED = "unresolved"
EVAL_CAPPED = "capped"

DEFAULT_EVALUATION_CAP = 96
DEFAULT_TIMEOUT_SECONDS = 20

SCHEMA_ID = "soundness-gate/1"

GATE_COVERAGE_CLAIM = (
    "gated: ledger_snapshot, untracked_modified_report; "
    "not gated (no pre-mutation candidate image is in hand on the route -- "
    "its image exists only once segments have been applied to an index): "
    "provenance_plan, checkpoint_provenance; "
    "not a landing (reads no candidate bytes and mutates nothing): classify"
)

# Whether a producer stops at its first error is MEASURED per check, never
# read off a list of kinds. A hand-maintained list is wrong the moment a
# predicate's behaviour differs from what the list assumed -- and it already
# would be here, because the document predicate is exhaustive over anchors
# but stops early on an unclosed fence, so one entry could not describe it.
# The measurement is: across every evaluation this invocation performed for
# that check, did the producer EVER return more than one diagnostic? If it
# never did, it may be masking a second defect and the reader is warned.
# The failure direction is over-warning, never a silent omission.

_HEADING_PREFIX_RE = re.compile(r"^(#{1,6})(\s|$)")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_BASH_LOCATION_PREFIX_RE = re.compile(r"^.*?:\s*line\s+\d+:\s*")
_BASH_LINE_RE = re.compile(r":\s*line\s+(\d+):")


# ===========================================================================
# Vocabulary introspection (AC5)
# ===========================================================================

def gate_vocabulary(records=None):
    """Every name this module DEFINES, derived by introspection.

    Two sources, both derived rather than maintained by hand: the module's own
    upper-case string constants, and -- when records are supplied -- every
    dict KEY those records actually emit. A constant added later is in the set
    the moment it exists; a field added later is in the set the moment it is
    emitted. Producer diagnostics and candidate-authored text are values, not
    keys or declared constants, and are therefore exempt by construction.
    """
    vocabulary = set()
    for name, value in sorted(globals().items()):
        if not name.isupper():
            continue
        vocabulary.add(name.lower())
        for item in _flatten_strings(value):
            vocabulary.add(item)
    for record in (records or []):
        vocabulary |= _dict_keys_deep(record)
    return frozenset(vocabulary)


def _flatten_strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for key, sub in value.items():
            out.extend(_flatten_strings(key))
            out.extend(_flatten_strings(sub))
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        out = []
        for sub in value:
            out.extend(_flatten_strings(sub))
        return out
    return []


def _dict_keys_deep(value):
    keys = set()
    if isinstance(value, dict):
        for key, sub in value.items():
            if isinstance(key, str):
                keys.add(key)
            keys |= _dict_keys_deep(sub)
    elif isinstance(value, (list, tuple)):
        for sub in value:
            keys |= _dict_keys_deep(sub)
    return keys


# ===========================================================================
# Discovery adapter -- replaceable, and null by default so the gate is
# exercisable with synthetic inputs and no repository at all.
# ===========================================================================

class NullDiscovery:
    """Discovers nothing. Every question resolves to the non-assertion answer.

    This is the default deliberately: a gate that silently assumed a role, a
    caller or an anchor set when it could discover none would reach a pass it
    had not earned.
    """

    method = "null-discovery: no consumer universe supplied"

    def invocation_role(self, normalized_path):
        return ROLE_UNKNOWN

    def callers(self, normalized_path):
        return []

    def json_role(self, normalized_path):
        return JSON_ROLE_UNKNOWN, "no tracked consumer universe supplied"

    def bound_schema(self, normalized_path):
        return None

    def required_anchors(self, normalized_path):
        return None

    def anchor_resolution_scheme(self, normalized_path):
        return None


class StaticDiscovery(NullDiscovery):
    """A discovery adapter whose answers are supplied rather than scanned.

    Used by offline exercises and by any caller that has already performed its
    own tracked-set enumeration. It records the method it was told, so the
    record still says how the answers were obtained.
    """

    def __init__(self, method="static-discovery: answers supplied by caller",
                 role=ROLE_UNKNOWN, callers=(), json_role=JSON_ROLE_UNKNOWN,
                 json_role_evidence="supplied", bound_schema=None,
                 required_anchors=None, anchor_scheme=None):
        self.method = method
        self._role = role
        self._callers = list(callers)
        self._json_role = json_role
        self._json_role_evidence = json_role_evidence
        self._bound_schema = bound_schema
        self._required_anchors = required_anchors
        self._anchor_scheme = anchor_scheme

    def invocation_role(self, normalized_path):
        return self._role

    def callers(self, normalized_path):
        return list(self._callers)

    def json_role(self, normalized_path):
        return self._json_role, self._json_role_evidence

    def bound_schema(self, normalized_path):
        return self._bound_schema

    def required_anchors(self, normalized_path):
        return self._required_anchors

    def anchor_resolution_scheme(self, normalized_path):
        return self._anchor_scheme


class TrackedSetDiscovery(NullDiscovery):
    """Discovery through ``git ls-files``, never through the shell's grep view.

    Tracked-set membership and .gitignore visibility are DIFFERENT predicates,
    and this repository diverges on both of them in BOTH directions: tracked
    files the shell's scan cannot see, and visible files that are not tracked.
    Under-derivation passes a document that broke a real consumer;
    over-derivation blocks a legitimate rename. So the consumer universe is
    enumerated through the index listing and each file is read directly.

    The DIRECT questions are answered by a SINGLE STREAMING PASS that holds one
    file at a time and retains only the small answer sets. Reading the whole
    tracked set into memory would answer the same questions and violate the
    resident-cost ceiling this work is bound by.

    The INDEXED question costs more than one pass, and says so rather than
    claiming otherwise: when the pass finds an index naming the candidate,
    _loader_chain re-walks the tracked Python to a fixed point to find the code
    that loads that index. Residency is unchanged -- still one file at a time,
    still only small answer sets, and the chain is cached per index -- but the
    pass COUNT is no longer one, and a docstring that still said SINGLE would
    be false.
    """

    _MODULE_LOAD_SIGNALS = (b"load_sibling_module", b"spec_from_file_location",
                            b"SourceFileLoader", b"runpy")
    _SCHEMA_COMPILE_SIGNALS = (b"check_schema", b"validator_for", b"jsonschema")
    _INSTANCE_VALIDATE_SIGNALS = (b"iter_errors", b"is_valid", b"validate(")
    _MAX_SOURCE_BYTES = 2 * 1024 * 1024
    def __init__(self, git_root, runner=None):
        self.git_root = git_root
        self._runner = runner or _run_git
        self.method = ("tracked-set discovery: single streaming pass over the "
                       "git ls-files enumeration under %s, files read "
                       "directly, one at a time; a path named as a path value "
                       "by an index is attributed the role of the tracked code "
                       "that loads that index" % git_root)
        self._tracked = None
        self._answers = {}
        self._chains = {}
        self._facts = {}

    def tracked(self):
        if self._tracked is None:
            code, out, _err = self._runner(self.git_root, ["ls-files", "-z"])
            self._tracked = ([] if code != 0 else
                             [p.decode("utf-8", "replace")
                              for p in out.split(b"\0") if p])
        return self._tracked

    def _own_bytes(self, normalized_path):
        full = os.path.join(self.git_root, normalized_path)
        try:
            with open(full, "rb") as handle:
                return handle.read()
        except OSError:
            return None

    def _py_facts(self, rel):
        """What REL actually loads, taken from its own SYNTAX: the module names
        it imports, and the path-shaped string literals it names.

        Byte containment was fail-open in both directions a reviewer can
        exploit: a short module name occurs inside unrelated longer words, and
        any name occurs in prose and in comments. An edge asserted from a
        substring is not an edge, so the edges are read off the parse.
        """
        if rel in self._facts:
            return self._facts[rel]
        imports, literals = set(), set()
        data = self._own_bytes(rel)
        tree = None
        if data is not None and len(data) <= self._MAX_SOURCE_BYTES:
            try:
                tree = ast.parse(data)
            except (SyntaxError, ValueError):
                tree = None
        for node in ast.walk(tree) if tree is not None else ():
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.update(alias.name.split("."))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.update(module.split("."))
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "." in node.value and not any(c.isspace()
                                                 for c in node.value):
                    literals.add(node.value)
        self._facts[rel] = (frozenset(imports), frozenset(literals))
        return self._facts[rel]

    def _loads(self, cand, item):
        """True iff CAND's own syntax shows it loading ITEM: an import of
        ITEM's module name when ITEM is Python, or a path-shaped literal
        naming ITEM otherwise."""
        imports, literals = self._py_facts(cand)
        base = posixpath.basename(item)
        if item.endswith(".py"):
            return base[:-3] in imports
        return any(lit == base or lit.endswith("/" + base) for lit in literals)

    @staticmethod
    def _string_values(value):
        """Every STRING VALUE in a parsed document, dict KEYS excluded.
        _flatten_strings yields keys as well, which would let {"x.json": 0}
        qualify as an index naming x.json. A key is a name the consumer looks
        up BY; only a value is a path the consumer goes on to read."""
        if isinstance(value, str):
            return [value]
        out = []
        if isinstance(value, dict):
            for sub in value.values():
                out.extend(TrackedSetDiscovery._string_values(sub))
        elif isinstance(value, (list, tuple)):
            for sub in value:
                out.extend(TrackedSetDiscovery._string_values(sub))
        return out

    @staticmethod
    def _names_as_path(data, target):
        """True iff DATA is a structured document that names TARGET as a PATH
        VALUE. Prose that merely contains the same bytes does not qualify: an
        index maps a key to a path, and that is the entire discriminator -- it
        is what lets the traversal be derived instead of enumerated."""
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False
        name = target.decode("utf-8")
        return any(value == name or value.endswith("/" + name)
                   for value in TrackedSetDiscovery._string_values(parsed))

    def _loader_chain(self, rel):
        """Tracked Python that loads REL -- directly, or through the modules
        that load it, to a FIXED POINT.

        The walk is bounded by the seen set, not by a depth constant. A depth
        tuned to today's index/loader/validator chain would be an enumeration
        of this repository's topology wearing a number's disguise, and one
        extra intermediary would silently return the role to unknown -- which
        is the same indeterminacy F1 was.

        Each edge is an EXACT load read off the candidate's parse -- an import
        of the module, or a path-shaped literal naming the file -- so the fixed
        point closes over the real load graph instead of fanning out across
        every file that happens to contain the name.
        """
        if rel in self._chains:
            return self._chains[rel]
        frontier, seen, out = {rel}, {rel}, []
        while frontier:
            current, frontier = frontier, set()
            for cand in self.tracked():
                if not cand.endswith(".py") or cand in seen:
                    continue
                if any(self._loads(cand, item) for item in current):
                    out.append(cand)
                    frontier.add(cand)
            seen |= frontier
        self._chains[rel] = sorted(set(out))
        return self._chains[rel]

    def _scan(self, normalized_path):
        """One pass; every question answered from the same traversal."""
        if normalized_path in self._answers:
            return self._answers[normalized_path]
        target = posixpath.basename(normalized_path).encode("utf-8")
        own = self._own_bytes(normalized_path)
        own_headings = [text for _level, text, _line in _headings(own or b"")]
        answers = {
            "module_loaders": [],
            "executors": [],
            "schema_compilers": [],
            "instance_validators": [],
            "index_referrers": [],
            "referenced_headings": set(),
        }
        for rel in self.tracked():
            if rel == normalized_path:
                continue
            full = os.path.join(self.git_root, rel)
            try:
                if os.path.getsize(full) > self._MAX_SOURCE_BYTES:
                    continue
                with open(full, "rb") as handle:
                    data = handle.read()
            except OSError:
                continue
            for heading in own_headings:
                if heading and heading.encode("utf-8") in data:
                    answers["referenced_headings"].add(heading)
            if target not in data:
                del data
                continue
            if rel.endswith(".py"):
                if any(sig in data for sig in self._MODULE_LOAD_SIGNALS):
                    answers["module_loaders"].append(rel)
                if any(sig in data for sig in self._SCHEMA_COMPILE_SIGNALS):
                    answers["schema_compilers"].append(rel)
                if any(sig in data for sig in self._INSTANCE_VALIDATE_SIGNALS):
                    answers["instance_validators"].append(rel)
            if b"subprocess" in data or b"#!/" in data:
                answers["executors"].append(rel)
            if not rel.endswith(".py") and self._names_as_path(data, target):
                answers["index_referrers"].append(rel)
            del data
        for key in ("module_loaders", "executors", "schema_compilers",
                    "instance_validators", "index_referrers"):
            answers[key].sort()
        self._answers[normalized_path] = answers
        return answers

    def invocation_role(self, normalized_path):
        answers = self._scan(normalized_path)
        if answers["module_loaders"]:
            return ROLE_MODULE_LOAD
        if answers["executors"]:
            return ROLE_DIRECT_EXECUTION
        if _extension_kind(normalized_path) in (KIND_JSON, KIND_MARKDOWN):
            return ROLE_DATA
        return ROLE_UNKNOWN

    def callers(self, normalized_path):
        out = []
        for rel in self._scan(normalized_path)["module_loaders"]:
            source = self._own_bytes(rel)
            if source is None:
                continue
            out.append({
                "caller_path": rel,
                "source": source,
                # The caller resolves the REPO-RELATIVE path, so that is
                # where the overlay places the candidate. It is still a
                # single-entry overlay: one file, at one path.
                "relative_target": normalized_path,
                "resolution_derivable": True,
            })
        return out

    def json_role(self, normalized_path):
        """Role from DISCOVERED TRACKED-CONSUMER EVIDENCE, never from the
        candidate's own keywords. A ``$schema`` declaration states how to READ
        a document; instances carry it too, so it is not evidence of
        schema-hood and is not consulted here."""
        answers = self._scan(normalized_path)
        if answers["schema_compilers"]:
            return (JSON_ROLE_SCHEMA,
                    "tracked consumer %s passes this path's parsed content to "
                    "a schema-compilation entry point"
                    % answers["schema_compilers"][0])
        if answers["instance_validators"]:
            return (JSON_ROLE_INSTANCE,
                    "tracked consumer %s validates this path against a schema"
                    % answers["instance_validators"][0])
        # R1b: a path a consumer never names itself, because it reaches it
        # THROUGH an index it also loads, still has that consumer's role.
        for referrer in answers["index_referrers"]:
            chain = self._loader_chain(referrer)
            for signals, role in ((self._SCHEMA_COMPILE_SIGNALS,
                                   JSON_ROLE_SCHEMA),
                                  (self._INSTANCE_VALIDATE_SIGNALS,
                                   JSON_ROLE_INSTANCE)):
                for caller in chain:
                    data = self._own_bytes(caller)
                    if data is None or not any(s in data for s in signals):
                        continue
                    return (role, "tracked consumer %s establishes this "
                            "path's role through the index %s it also loads"
                            % (caller, referrer))
        return (JSON_ROLE_UNKNOWN,
                "no tracked consumer loads this path as a schema or validates "
                "it against one")

    def required_anchors(self, normalized_path):
        if self._own_bytes(normalized_path) is None:
            return None
        return set(self._scan(normalized_path)["referenced_headings"])

    def anchor_resolution_scheme(self, normalized_path):
        return "ordinal"


def _run_git(git_root, args):
    proc = subprocess.run(["git", "-C", git_root] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


# ===========================================================================
# Span and coordinate contract (R3a)
# ===========================================================================

def line_spans(data):
    """Zero-based half-open BYTE spans, one per physical line, each INCLUDING
    its terminator. No newline, BOM or trailing-newline normalisation is
    applied before the offsets are taken: a span must address the bytes that
    actually land."""
    spans = []
    start = 0
    length = len(data)
    while start < length:
        cut = data.find(b"\n", start)
        if cut == -1:
            spans.append((start, length))
            break
        spans.append((start, cut + 1))
        start = cut + 1
    return spans


def _span_for_line(data, lineno):
    spans = line_spans(data)
    if lineno is None or lineno < 1 or lineno > len(spans):
        return (len(data), len(data)), True
    return spans[lineno - 1], False


def _python_error_span(data, exc):
    """Convert a CPython SyntaxError position into a byte span.

    ``offset`` counts code points of the DECODED line, so the prefix is
    re-encoded in the encoding the compiler itself detected -- the PEP 263
    declaration or the BOM the candidate carries -- never an assumed UTF-8.
    """
    span, at_eof = _span_for_line(data, getattr(exc, "lineno", None))
    if at_eof:
        return span, True, True
    offset = getattr(exc, "offset", None)
    if not offset or offset < 1:
        return span, True, False
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except (SyntaxError, UnicodeDecodeError):
        return span, True, False
    raw_line = data[span[0]:span[1]]
    try:
        decoded = raw_line.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return span, True, False
    prefix = decoded[:offset - 1]
    try:
        delta = len(prefix.encode(encoding))
    except (UnicodeEncodeError, LookupError):
        return span, True, False
    point = min(span[0] + delta, span[1])
    return (point, min(point + 1, span[1])), False, False


def _json_error_span(data, exc):
    encoding = json.detect_encoding(data)
    try:
        text = data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        span, _ = _span_for_line(data, getattr(exc, "lineno", None))
        return span, True, False
    pos = getattr(exc, "pos", None)
    if pos is None:
        span, _ = _span_for_line(data, getattr(exc, "lineno", None))
        return span, True, False
    if pos >= len(text):
        return (len(data), len(data)), False, True
    try:
        point = len(text[:pos].encode(encoding))
    except (UnicodeEncodeError, LookupError):
        span, _ = _span_for_line(data, getattr(exc, "lineno", None))
        return span, True, False
    return (point, min(point + 1, len(data))), False, False


# ===========================================================================
# Kind detection (R17)
# ===========================================================================

def normalize_path(path):
    """Repo-relative, POSIX separators, no leading ``./``.

    Detection keys on THIS string, never on a declared path that carries
    annotation text, because an annotated declaration is a hygiene defect of
    the producer and must not change which predicate runs.
    """
    if path is None:
        return None
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return posixpath.normpath(text) if text else text


_EXTENSION_TOKEN_RE = re.compile(r"^\.([A-Za-z0-9_+-]+)")


def _extension_kind(normalized):
    """The kind carried by the NORMALIZED path's extension.

    Two derivations, neither of them a list of special cases:

    1. The extension token is the leading run of extension-legal characters
       after the final dot. That is what keeps an annotation-bearing declared
       string -- a path field carrying trailing commentary -- from changing
       the selected kind, without needing to know any particular annotation
       shape. The declaration hygiene defect is the producer's; mis-routing
       because of it would be this gate's.
    2. A token the predicate registry names maps to that canonical kind;
       any OTHER well-formed token IS the detected kind, under its own name.
       This is what makes "detected, but no parser is declared for it"
       reachable and distinct from "no kind could be detected at all" -- two
       different facts that a single unrecognised-extension branch would
       collapse into one.
    """
    if not normalized:
        return None
    _stem, ext = posixpath.splitext(normalized)
    match = _EXTENSION_TOKEN_RE.match(ext)
    if not match:
        return None
    token = "." + match.group(1).lower()
    return EXTENSION_KIND_REGISTRY.get(token, token[1:])


def _shebang_kind(data):
    if not data.startswith(b"#!"):
        return None
    newline = data.find(b"\n")
    line = data[2:] if newline == -1 else data[2:newline]
    try:
        text = line.decode("utf-8", "replace").strip()
    except Exception:  # pragma: no cover - decode with replace cannot raise
        return None
    if not text:
        return None
    words = text.split()
    candidate = posixpath.basename(words[0])
    if candidate == "env" and len(words) > 1:
        candidate = posixpath.basename(words[1])
    candidate = candidate.split("-")[0] if candidate.startswith("python-") \
        else candidate
    return INTERPRETER_KIND_REGISTRY.get(candidate)


def detect_kind(normalized_path, data, invocation_role,
                interpreter_contract=None):
    """The R17 precedence, evaluated in order, recording the clause that fired.

    A shebang governs kernel exec dispatch only. For a file that is IMPORTED
    it is a comment -- the bytes are parsed by the language regardless of what
    the first line names -- so an imported module is decided by its extension,
    not by its shebang.
    """
    extension_kind = _extension_kind(normalized_path)
    shebang_kind = _shebang_kind(data or b"")
    record = {
        "extension_kind": extension_kind,
        "shebang_kind": shebang_kind,
        "invocation_role": invocation_role,
        "selected": None,
        "precedence_rule": None,
        "disagreement": bool(extension_kind and shebang_kind
                             and extension_kind != shebang_kind),
        "reason": None,
    }
    if extension_kind and shebang_kind and extension_kind == shebang_kind:
        record["selected"] = extension_kind
        record["precedence_rule"] = "R17.0_both_signals_agree"
        return record
    if interpreter_contract:
        kind = INTERPRETER_KIND_REGISTRY.get(
            posixpath.basename(str(interpreter_contract)))
        if kind:
            record["selected"] = kind
            record["precedence_rule"] = "R17.1_discovered_invocation_contract"
            return record
    if invocation_role in (ROLE_MODULE_LOAD, ROLE_DATA) and extension_kind:
        record["selected"] = extension_kind
        record["precedence_rule"] = "R17.2_role_is_module_load_or_data"
        return record
    if shebang_kind and (invocation_role == ROLE_DIRECT_EXECUTION
                         or not extension_kind):
        record["selected"] = shebang_kind
        record["precedence_rule"] = "R17.3_shebang_for_direct_execution"
        return record
    conclusive = [k for k in (extension_kind, shebang_kind) if k]
    if len(conclusive) == 1:
        record["selected"] = conclusive[0]
        record["precedence_rule"] = "R17.4_single_conclusive_signal"
        return record
    if extension_kind and shebang_kind:
        record["precedence_rule"] = "R17.5_unresolved_disagreement"
        record["reason"] = REASON_KIND_SIGNAL_DISAGREEMENT
        return record
    record["precedence_rule"] = "R17.6_neither_signal_conclusive"
    record["reason"] = REASON_KIND_UNDETECTABLE
    return record


# ===========================================================================
# Diagnostics
# ===========================================================================

class Diagnostic:
    """One producer finding, reduced to a comparable key plus a byte span."""

    __slots__ = ("check", "kind", "diagnostic_class", "message", "span",
                 "at_eof", "column_unavailable")

    def __init__(self, check, kind, diagnostic_class, message, span=None,
                 at_eof=False, column_unavailable=False):
        self.check = check
        self.kind = kind
        self.diagnostic_class = diagnostic_class
        self.message = message
        self.span = span
        self.at_eof = at_eof
        self.column_unavailable = column_unavailable

    @property
    def key(self):
        """(check, kind, class, normalised message).

        Normalisation is LOCATION-ONLY. Semantic integers and
        repository-relative paths are meaning, not position, and stripping
        them erases real regressions.
        """
        return (self.check, self.kind, self.diagnostic_class, self.message)

    def as_dict(self):
        payload = {
            "check": self.check,
            "detected_kind": self.kind,
            "diagnostic_class": self.diagnostic_class,
            "message_normalised": self.message,
        }
        if self.at_eof:
            payload["position"] = LOCATION_AT_EOF
        if self.span is not None:
            payload["span"] = list(self.span)
        if self.column_unavailable:
            payload["column_unavailable"] = True
        return payload


def _normalise_producer_message(text, temp_roots=()):
    out = text or ""
    for root in temp_roots:
        if root:
            out = out.replace(root, "<private-temporary-root>")
    out = _BASH_LOCATION_PREFIX_RE.sub("", out)
    return out.strip()


# ===========================================================================
# markdown_doc structural view (R1a / R2 for documents)
# ===========================================================================

def _document_view(data):
    """One frozen validation view: physical lines, fence state, headings.

    Evaluated on exactly the same view for the baseline and for the candidate,
    because a hierarchy invariant compared across two different views proves
    nothing.
    """
    spans = line_spans(data)
    fence = None
    fence_open_line = None
    headings = []
    for index, (start, end) in enumerate(spans, start=1):
        raw = data[start:end]
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:  # pragma: no cover
            text = ""
        stripped = text.rstrip("\r\n")
        lead = stripped[:4]
        body = stripped.lstrip(" ")
        if len(lead) - len(lead.lstrip(" ")) > 3:
            body = stripped
        match = _FENCE_RE.match(body)
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
                fence_open_line = index
                continue
            if marker == fence:
                fence = None
                fence_open_line = None
            continue
        if fence is not None:
            continue
        heading = _HEADING_PREFIX_RE.match(body)
        if heading:
            level = len(heading.group(1))
            headings.append((level, body[level:].strip(), index))
    return {
        "spans": spans,
        "headings": headings,
        "unclosed_fence_line": fence_open_line if fence is not None else None,
    }


def _headings(data):
    return _document_view(data)["headings"]


def _dominating_chain(headings, position):
    """The ordered chain of nearest preceding headings of strictly smaller
    level -- the structure a consumer walks to resolve an anchor's block."""
    level = headings[position][0]
    chain = []
    current = level
    for index in range(position - 1, -1, -1):
        candidate_level, text, _line = headings[index]
        if candidate_level < current:
            chain.append((candidate_level, text))
            current = candidate_level
            if current == 1:
                break
    chain.reverse()
    return tuple(chain)


def _anchor_occurrences(view, anchor):
    out = []
    headings = view["headings"]
    for position, (level, text, line) in enumerate(headings):
        if text == anchor:
            out.append({
                "level": level,
                "line": line,
                "chain": _dominating_chain(headings, position),
            })
    return out


# ===========================================================================
# SC-1 predicates
# ===========================================================================

def _sc1_python(data, _ctx):
    try:
        compile(data, "<candidate>", "exec")
    except SyntaxError as exc:
        span, column_unavailable, at_eof = _python_error_span(data, exc)
        return [Diagnostic(CHECK_SC1, KIND_PYTHON, type(exc).__name__,
                           _normalise_producer_message(exc.msg), span,
                           at_eof=at_eof,
                           column_unavailable=column_unavailable)]
    except ValueError as exc:
        return [Diagnostic(CHECK_SC1, KIND_PYTHON, type(exc).__name__,
                           _normalise_producer_message(str(exc)),
                           (0, len(data)))]
    return []


def _sc1_shell(data, ctx):
    with ctx.workspace(data) as space:
        proc = ctx.run([ctx.shell_binary, "-n", space.target],
                       cwd=ctx.outside_root)
    if proc.returncode == 0:
        return []
    stderr = (proc.stderr or b"").decode("utf-8", "replace")
    diagnostics = []
    for raw in stderr.splitlines():
        if not raw.strip():
            continue
        match = _BASH_LINE_RE.search(raw)
        lineno = int(match.group(1)) if match else None
        span, at_eof = _span_for_line(data, lineno)
        diagnostics.append(Diagnostic(
            CHECK_SC1, KIND_SHELL, "parse-error",
            _normalise_producer_message(raw, ctx.temp_roots()), span,
            at_eof=at_eof, column_unavailable=True))
    if not diagnostics:
        diagnostics.append(Diagnostic(
            CHECK_SC1, KIND_SHELL, "parse-error",
            "non-zero syntax-check exit with no diagnostic text",
            (len(data), len(data)), at_eof=True, column_unavailable=True))
    return diagnostics


def _sc1_json(data, _ctx):
    try:
        json.loads(data)
    except json.JSONDecodeError as exc:
        span, column_unavailable, at_eof = _json_error_span(data, exc)
        return [Diagnostic(CHECK_SC1, KIND_JSON, "JSONDecodeError",
                           _normalise_producer_message(exc.msg), span,
                           at_eof=at_eof,
                           column_unavailable=column_unavailable)]
    except (UnicodeDecodeError, ValueError) as exc:
        return [Diagnostic(CHECK_SC1, KIND_JSON, type(exc).__name__,
                           _normalise_producer_message(str(exc)),
                           (0, len(data)))]
    return []


def _sc1_markdown(data, ctx):
    view = _document_view(data)
    diagnostics = []
    if view["unclosed_fence_line"] is not None:
        span, at_eof = _span_for_line(data, view["unclosed_fence_line"])
        diagnostics.append(Diagnostic(
            CHECK_SC1, KIND_MARKDOWN, "unclosed-fence",
            "a fenced block opened here is not closed before end of file",
            span, at_eof=at_eof, column_unavailable=True))
        return diagnostics
    baseline_view = ctx.baseline_document_view()
    anchors = ctx.required_anchor_set()
    if baseline_view is None or anchors is None:
        return diagnostics
    for anchor in sorted(anchors):
        before = _anchor_occurrences(baseline_view, anchor)
        after = _anchor_occurrences(view, anchor)
        if len(before) != len(after):
            span, at_eof = _span_for_line(
                data, after[0]["line"] if after else None)
            diagnostics.append(Diagnostic(
                CHECK_SC1, KIND_MARKDOWN, "anchor-occurrence-count",
                "required anchor %r occurs %d times, %d in the baseline"
                % (anchor, len(after), len(before)), span, at_eof=at_eof,
                column_unavailable=True))
            continue
        for ordinal, (was, now) in enumerate(zip(before, after), start=1):
            span, at_eof = _span_for_line(data, now["line"])
            if was["level"] != now["level"]:
                diagnostics.append(Diagnostic(
                    CHECK_SC1, KIND_MARKDOWN, "anchor-level-change",
                    "required anchor %r occurrence %d is at level %d, %d in "
                    "the baseline" % (anchor, ordinal, now["level"],
                                      was["level"]), span, at_eof=at_eof,
                    column_unavailable=True))
            elif was["chain"] != now["chain"]:
                diagnostics.append(Diagnostic(
                    CHECK_SC1, KIND_MARKDOWN, "anchor-reparented",
                    "required anchor %r occurrence %d is dominated by %r, by "
                    "%r in the baseline" % (anchor, ordinal,
                                            list(now["chain"]),
                                            list(was["chain"])), span,
                    at_eof=at_eof, column_unavailable=True))
    return diagnostics


SC1_REGISTRY = {
    KIND_PYTHON: _sc1_python,
    KIND_SHELL: _sc1_shell,
    KIND_JSON: _sc1_json,
    KIND_MARKDOWN: _sc1_markdown,
}


# ===========================================================================
# SC-2 predicates
# ===========================================================================

class NotAsserted(Exception):
    """A mandatory check could not be RUN. Never a pass, never a failure."""

    def __init__(self, reason, detail=None, extra=None):
        self.reason = reason
        self.detail = detail
        self.extra = extra or {}
        Exception.__init__(self, reason if detail is None
                           else "%s: %s" % (reason, detail))


_AUDIT_SITECUSTOMIZE = '''\
import hashlib
import os
import sys

_target = os.environ.get("SOUNDNESS_GATE_AUDIT")
_busy = [False]


def _hook(event, args):
    if event != "open" or _busy[0] or not _target:
        return
    _busy[0] = True
    try:
        path = args[0]
        if isinstance(path, bytes):
            path = path.decode("utf-8", "replace")
        if not isinstance(path, str) or not os.path.isfile(path):
            return
        handle = os.open(path, os.O_RDONLY)
        try:
            chunks = []
            while True:
                block = os.read(handle, 65536)
                if not block:
                    break
                chunks.append(block)
        finally:
            os.close(handle)
        digest = hashlib.sha256(b"".join(chunks)).hexdigest()
        out = os.open(_target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(out, (digest + "\\n").encode("ascii"))
        finally:
            os.close(out)
    except Exception:
        pass
    finally:
        _busy[0] = False


if _target:
    sys.addaudithook(_hook)
'''


def plan_smoke_form(data, ctx):
    """Discover the SC-2 entry form ONCE, against the candidate image.

    Frozen for the whole invocation, for two reasons that are not stylistic.
    First, whether a check can be RUN is a property of the candidate, not of
    an arbitrary sub-combination -- deciding it on the baseline image made a
    perfectly assertable candidate report as unassertable. Second, a witness
    search whose predicate can change between evaluations is comparing
    different questions, so its minimal set means nothing.

    Forms are tried in order, every form attempted is recorded, and a form
    that exits before it reaches its load site has demonstrated nothing: it is
    ``not_run`` and FALLS THROUGH to the next discovered form. SC-2 is
    unrunnable only when every discovered form reaches ``not_run`` or none is
    available.
    """
    attempts = []
    for caller in ctx.discovery.callers(ctx.normalized_path):
        outcome = _try_caller_form(data, ctx, caller, ctx.content_sha256)
        attempts.append(_planning_view(outcome))
        if outcome["state"] == STATE_RAN:
            return {"form": SMOKE_FORM_CALLER, "caller": caller,
                    "attempts": attempts, "substitution_reason": None}
        if outcome.get("terminal"):
            return {"form": None, "attempts": attempts,
                    "reason": outcome["reason"],
                    "detail": outcome.get("detail"),
                    "substitution_reason": outcome.get("detail")}
    for form, flag in ((SMOKE_FORM_HELP, "--help"),
                       (SMOKE_FORM_DRY_RUN, "--dry-run")):
        outcome = _try_flag_form(data, ctx, form, flag)
        attempts.append(_planning_view(outcome))
        if outcome["state"] == STATE_RAN:
            return {"form": form, "flag": flag, "attempts": attempts,
                    "substitution_reason": None}
    if attempts and all(a["state"] == STATE_NOT_RUN for a in attempts):
        return {"form": None, "attempts": attempts,
                "reason": REASON_ALL_ENTRY_FORMS_NOT_RUN,
                "detail": "every discovered entry form exited before it "
                          "reached its load site",
                "substitution_reason": None}
    return {"form": None, "attempts": attempts,
            "reason": REASON_NO_SIDE_EFFECT_FREE_ENTRY_FORM,
            "detail": ctx.discovery.method, "substitution_reason": None}


def _planning_view(outcome):
    view = {k: v for k, v in outcome.items() if k != "diagnostics"}
    view["produced_diagnostics"] = len(outcome.get("diagnostics") or [])
    return view


def _sc2_script(data, ctx):
    """Execute the FROZEN entry form against this selection's image."""
    plan = ctx.smoke_plan or {}
    if plan.get("form") is None:
        raise NotAsserted(plan.get("reason",
                                   REASON_NO_SIDE_EFFECT_FREE_ENTRY_FORM),
                          plan.get("detail"),
                          {"smoke_attempts": plan.get("attempts", [])})
    digest = hashlib.sha256(data).hexdigest()
    if plan["form"] == SMOKE_FORM_CALLER:
        outcome = _try_caller_form(data, ctx, plan["caller"], digest)
        if outcome["state"] != STATE_RAN:
            # This image could not be exercised through the frozen form. It is
            # neither a pass nor a failure; it is an evaluation the search
            # could not resolve.
            raise _UnresolvedEvaluation(
                "the frozen entry form did not reach its load site on this "
                "sub-combination")
        return outcome["diagnostics"]
    outcome = _run_frozen_flag_form(data, ctx, plan["flag"])
    return outcome["diagnostics"]


class _UnresolvedEvaluation(Exception):
    """This particular evaluation could not be resolved; the search records it
    as unresolved and never counts it as a pass."""


def _run_frozen_flag_form(data, ctx, flag):
    relative = ctx.normalized_path
    with ctx.workspace(data, relative=relative, executable=True) as space:
        proc = ctx.run(ctx.interpreter_argv(space.target) + [flag],
                       cwd=space.overlay_root,
                       env=ctx.child_env(space.overlay_root))
    outcome = {"exit_code": proc.returncode, "diagnostics": []}
    if proc.returncode == 0:
        return outcome
    combined = ((proc.stdout or b"") + (proc.stderr or b"")).decode(
        "utf-8", "replace").strip()
    outcome["diagnostics"] = [Diagnostic(
        CHECK_SC2, ctx.detected_kind, "entry-form-invocation",
        _normalise_producer_message(combined.splitlines()[-1] if combined
                                    else "non-zero exit", ctx.temp_roots()))]
    return outcome


def _try_caller_form(data, ctx, caller, expected_digest):
    outcome = {"form": SMOKE_FORM_CALLER,
               "caller_path": caller.get("caller_path"),
               "state": STATE_NOT_RUN, "diagnostics": [],
               "substitution": None}
    if not caller.get("resolution_derivable", False) \
            or caller.get("side_effect_free") is False:
        outcome["state"] = STATE_UNAVAILABLE
        outcome["terminal"] = True
        outcome["reason"] = REASON_CALLER_NOT_EQUIVALENT
        outcome["detail"] = ("the discovered caller cannot be invoked "
                             "side-effect-free, or its path-resolution "
                             "mechanism is not derivable, and no mechanical "
                             "analysis proves the loader primitive "
                             "observationally equivalent")
        return outcome
    relative = caller.get("relative_target") or ctx.normalized_path
    with ctx.workspace(data, relative=relative) as space:
        if True:
            root = space.overlay_root
            support = space.harness_root
            caller_file = os.path.join(support, "discovered_caller.py")
            with open(caller_file, "wb") as handle:
                handle.write(caller["source"] if isinstance(
                    caller["source"], bytes)
                    else str(caller["source"]).encode("utf-8"))
            audit_dir = os.path.join(support, "audit")
            os.makedirs(audit_dir, exist_ok=True)
            with open(os.path.join(audit_dir, "sitecustomize.py"),
                      "w", encoding="utf-8") as handle:
                handle.write(_AUDIT_SITECUSTOMIZE)
            audit_log = os.path.join(support, "opened.txt")
            env = ctx.child_env(root)
            env["PYTHONPATH"] = audit_dir
            env["SOUNDNESS_GATE_AUDIT"] = audit_log
            proc = ctx.run([sys.executable, caller_file], cwd=root, env=env)
            observed = set()
            if os.path.isfile(audit_log):
                with open(audit_log, "r", encoding="utf-8") as handle:
                    observed = {line.strip() for line in handle if line.strip()}
    outcome["reached_load_site"] = expected_digest in observed
    outcome["exit_code"] = proc.returncode
    if not outcome["reached_load_site"]:
        outcome["state"] = STATE_NOT_RUN
        outcome["detail"] = ("the caller returned without opening bytes whose "
                             "digest equals the candidate's")
        return outcome
    outcome["state"] = STATE_RAN
    if proc.returncode != 0:
        message = (proc.stderr or b"").decode("utf-8", "replace").strip()
        outcome["diagnostics"] = [Diagnostic(
            CHECK_SC2, ctx.detected_kind, "caller-invocation",
            _normalise_producer_message(message.splitlines()[-1]
                                        if message else "non-zero exit",
                                        ctx.temp_roots()))]
    return outcome


def _try_flag_form(data, ctx, form, flag):
    """Availability of this form is MEASURED against a control, never assumed.

    A candidate that ignores its arguments exits 0 for every flag, so an exit
    code of 0 under the real flag proves nothing on its own -- that is a
    predicate which cannot fail, and a predicate which cannot fail is not
    evidence. The form is therefore probed twice: once with a nonce flag no
    declared surface can recognise, and once with the real flag. Only a
    DIFFERENCE between the two shows that the candidate has an argument
    surface at all. When the two agree the form is recorded unavailable, which
    routes to non-assertion rather than to a pass.
    """
    outcome = {"form": form, "state": STATE_UNAVAILABLE, "diagnostics": [],
               "substitution": None}
    relative = ctx.normalized_path
    control_flag = "--" + hashlib.sha256(
        (flag + ctx.content_sha256).encode("utf-8")).hexdigest()[:24]
    with ctx.workspace(data, relative=relative, executable=True) as space:
        root, target = space.overlay_root, space.target
        control = ctx.run(ctx.interpreter_argv(target) + [control_flag],
                          cwd=root, env=ctx.child_env(root))
        proc = ctx.run(ctx.interpreter_argv(target) + [flag], cwd=root,
                       env=ctx.child_env(root))
    outcome["exit_code"] = proc.returncode
    outcome["control_exit_code"] = control.returncode
    outcome["control_flag_discriminates"] = (
        control.returncode != proc.returncode)
    if not outcome["control_flag_discriminates"]:
        # The candidate answers an unrecognisable flag exactly as it answers
        # this one: it declares no surface of this shape.
        return outcome
    outcome["state"] = STATE_RAN
    if proc.returncode == 0:
        return outcome
    combined = ((proc.stdout or b"") + (proc.stderr or b"")).decode(
        "utf-8", "replace").strip()
    outcome["diagnostics"] = [Diagnostic(
        CHECK_SC2, ctx.detected_kind, "entry-form-invocation",
        _normalise_producer_message(combined.splitlines()[-1] if combined
                                    else "non-zero exit",
                                    ctx.temp_roots()))]
    return outcome


def _sc2_json(data, ctx):
    """The declared consumer contract. ``json_role`` comes from discovered
    tracked-consumer evidence; a ``$schema`` keyword is never taken as proof of
    schema-hood, because instances carry it too."""
    role, evidence = ctx.json_role()
    ctx.note("json_role", role)
    ctx.note("json_role_evidence", evidence)
    if role == JSON_ROLE_UNKNOWN:
        raise NotAsserted(REASON_NO_DECLARED_CONSUMER_CONTRACT,
                          evidence, {"json_role": role,
                                     "discovery_method": ctx.discovery.method})
    try:
        parsed = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        return [Diagnostic(CHECK_SC2, KIND_JSON, "unparseable-for-contract",
                           _normalise_producer_message(str(exc)),
                           (0, len(data)))]
    if role == JSON_ROLE_SCHEMA:
        return _validate_as_schema(parsed, data)
    bound = ctx.discovery.bound_schema(ctx.normalized_path)
    if bound is None:
        raise NotAsserted(REASON_NO_DECLARED_CONSUMER_CONTRACT,
                          "a tracked consumer binds this path to a schema but "
                          "that schema is not resolvable",
                          {"json_role": role})
    return _validate_against_schema(parsed, bound, data)


def _jsonschema():
    try:
        import jsonschema  # noqa: PLC0415 - optional dependency, probed here
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise NotAsserted(REASON_NO_DECLARED_CONSUMER_CONTRACT,
                          "no structured-data validator is available: %s"
                          % exc)
    return jsonschema


def _validate_as_schema(parsed, data):
    jsonschema = _jsonschema()
    declared = parsed.get("$schema") if isinstance(parsed, dict) else None
    validator = None
    if declared is not None:
        validator = jsonschema.validators.validator_for(parsed, default=None)
        if validator is None:
            raise NotAsserted(REASON_UNSUPPORTED_SCHEMA_DIALECT,
                              "the declared dialect is not available to the "
                              "validator, and validating under a fallback "
                              "draft would assert more than was proven")
    if validator is None:
        validator = jsonschema.validators.validator_for(parsed)
    try:
        validator.check_schema(parsed)
    except Exception as exc:  # jsonschema raises SchemaError subclasses
        return [Diagnostic(CHECK_SC2, KIND_JSON, "schema-compilation",
                           _normalise_producer_message(
                               getattr(exc, "message", str(exc))),
                           (0, len(data)))]
    return []


def _validate_against_schema(parsed, schema, data):
    jsonschema = _jsonschema()
    validator = jsonschema.validators.validator_for(schema, default=None)
    if validator is None:
        raise NotAsserted(REASON_UNSUPPORTED_SCHEMA_DIALECT,
                          "the dialect the bound schema declares is not "
                          "available to the validator")
    errors = sorted(validator(schema).iter_errors(parsed),
                    key=lambda e: (list(e.absolute_path), e.message))
    return [Diagnostic(CHECK_SC2, KIND_JSON, "instance-validation",
                       _normalise_producer_message(
                           "/".join(str(p) for p in error.absolute_path)
                           + ": " + error.message),
                       (0, len(data)))
            for error in errors]


def _sc2_markdown(data, ctx):
    """Required-anchor preservation: existence, non-splitting, and -- where the
    requiring consumer's addressing scheme is derivable -- resolution to the
    same ordinal occurrence. Structural evidence alone never produces a pass,
    because that would assert more than was proven."""
    anchors = ctx.required_anchor_set()
    baseline_view = ctx.baseline_document_view()
    if anchors is None or baseline_view is None:
        raise NotAsserted(REASON_NO_DECLARED_CONSUMER_CONTRACT,
                          "the required-anchor set is not derivable from the "
                          "tracked consumer universe",
                          {"discovery_method": ctx.discovery.method})
    scheme = ctx.discovery.anchor_resolution_scheme(ctx.normalized_path)
    if anchors and scheme is None:
        raise NotAsserted(REASON_ANCHOR_SCHEME_UNDERIVABLE,
                          "the requiring consumer's addressing scheme could "
                          "not be derived, so ordinal-resolution equivalence "
                          "cannot be asserted")
    view = _document_view(data)
    diagnostics = []
    for anchor in sorted(anchors):
        before = _anchor_occurrences(baseline_view, anchor)
        after = _anchor_occurrences(view, anchor)
        if not before:
            continue
        if not after:
            diagnostics.append(Diagnostic(
                CHECK_SC2, KIND_MARKDOWN, "required-anchor-absent",
                "required anchor %r is present in the baseline and absent "
                "from the candidate" % anchor, (len(data), len(data)),
                at_eof=True, column_unavailable=True))
            continue
        if len(before) != len(after):
            span, at_eof = _span_for_line(data, after[0]["line"])
            diagnostics.append(Diagnostic(
                CHECK_SC2, KIND_MARKDOWN, "required-anchor-ordinal",
                "required anchor %r resolves to %d occurrences, %d in the "
                "baseline" % (anchor, len(after), len(before)), span,
                at_eof=at_eof, column_unavailable=True))
    return diagnostics


SC2_REGISTRY = {
    KIND_PYTHON: _sc2_script,
    KIND_SHELL: _sc2_script,
    KIND_JSON: _sc2_json,
    KIND_MARKDOWN: _sc2_markdown,
}

SC2_PREDICATE_NAME = {
    KIND_PYTHON: "caller_or_help_or_dryrun",
    KIND_SHELL: "caller_or_help_or_dryrun",
    KIND_JSON: SMOKE_FORM_CONSUMER_CONTRACT,
    KIND_MARKDOWN: SMOKE_FORM_ANCHOR_PRESERVATION,
}


# ===========================================================================
# Composer conformance (R16 / D1)
# ===========================================================================

class ComposerRejected(Exception):
    def __init__(self, reason, detail):
        self.reason = reason
        self.detail = detail
        Exception.__init__(self, "%s: %s" % (reason, detail))


def _attr(result, name):
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _check_bijection(result, requested):
    """One region denotes exactly one atomic hunk, and region -> hunk_id is a
    BIJECTION onto the exact set of hunk ids the gate requested of compose().

    Totality and injectivity alone are insufficient: without surjectivity a
    composed hunk can exist with no region and be invisible to the witness
    search, which is precisely how a coarse producer passes a review it should
    fail. Surjectivity is therefore decided against the REQUESTED selection,
    never against whatever the producer chose to emit.
    """
    region_index = _attr(result, "region_index")
    if not isinstance(region_index, dict):
        raise ComposerRejected(REASON_REGION_GRANULARITY,
                               "the producer emitted no region index")
    seen = []
    for region_id, region in region_index.items():
        hunk_id = _attr(region, "hunk_id")
        if hunk_id is None:
            raise ComposerRejected(
                REASON_REGION_GRANULARITY,
                "region %r carries no hunk id, so the mapping is not total"
                % (region_id,))
        seen.append(hunk_id)
    if len(set(seen)) != len(seen):
        raise ComposerRejected(
            REASON_REGION_GRANULARITY,
            "several regions denote the same hunk, so the mapping is not "
            "injective and a hunk cannot be selected on its own")
    if set(seen) != set(requested):
        missing = sorted(set(requested) - set(seen), key=repr)
        extra = sorted(set(seen) - set(requested), key=repr)
        raise ComposerRejected(
            REASON_REGION_GRANULARITY,
            "the region index is not onto the requested selection "
            "(unrepresented: %r; unrequested: %r), so a composed hunk would "
            "be invisible to the witness search" % (missing, extra))


# ===========================================================================
# Evaluation context
# ===========================================================================

class _Context:
    """Everything one gate invocation needs, plus the resource discipline.

    Sub-combinations are evaluated SERIALLY. At most one composed byte image
    and one temporary artifact are live at any instant and both are released
    before the next evaluation begins; only scalar results plus the selection
    listing are retained across evaluations. No checkout, clone or tree copy
    is ever created -- including by the smoke harness, which materialises a
    single-entry overlay.
    """

    def __init__(self, composer, discovery, evaluation_cap, timeout,
                 observer, shell_binary):
        self.composer = composer
        self.discovery = discovery or NullDiscovery()
        self.evaluation_cap = evaluation_cap
        self.timeout = timeout
        self.observer = observer
        self.shell_binary = shell_binary
        self.evaluations_performed = 0
        self.cap_reached = False
        self.unresolved_count = 0
        self.unresolved_reasons = []
        self._cache = {}
        self.max_diagnostics = {}
        self._temp_roots = []
        self._live_images = weakref.WeakSet()
        self.max_live_images = 0
        self.live_temp_artifacts = 0
        self.max_live_temp_artifacts = 0
        self.outside_root = tempfile.gettempdir()
        self.normalized_path = None
        self.detected_kind = None
        self.content_sha256 = None
        self.notes = {}
        self.smoke_plan = None
        self._baseline_bytes = None
        self._baseline_view = None
        self._anchor_set = None
        self._anchor_derived = False
        self._json_role = None

    # -- notes -------------------------------------------------------------
    def note(self, key, value):
        self.notes[key] = value

    def first_error_only(self, check):
        """Measured, not declared: the producer never returned more than one
        diagnostic across the evaluations this invocation performed, so it may
        be stopping at its first error and masking a second defect."""
        return self.max_diagnostics.get(check, 0) <= 1

    # -- temp discipline ---------------------------------------------------
    def temp_roots(self):
        return list(self._temp_roots)

    class _Workspace:
        """ONE temporary artifact per exercise, and only one live at a time.

        The candidate's own root -- the directory the discovered caller
        resolves against, and the subprocess's working directory -- holds
        EXACTLY the candidate, at exactly one relative path. The harness the
        exercise needs (the discovered caller's own source, the audit hook)
        lives in a SIBLING subtree of the same single temporary root, so it
        is neither visible inside the overlay nor a second artifact to
        account for. Counting the harness as a separate live artifact, or
        omitting it from the count, were the two dishonest options; giving
        the exercise one root is the honest one.
        """

        def __init__(self, ctx, data, relative, executable):
            self.ctx = ctx
            self.data = data
            self.relative = relative
            self.executable = executable
            self.root = None
            self.overlay_root = None
            self.harness_root = None

        def __enter__(self):
            self.root = tempfile.mkdtemp(prefix="soundness-gate-workspace-")
            self.ctx._temp_roots.append(self.root)
            self.ctx.live_temp_artifacts += 1
            self.ctx.max_live_temp_artifacts = max(
                self.ctx.max_live_temp_artifacts, self.ctx.live_temp_artifacts)
            self.overlay_root = os.path.join(self.root, "overlay")
            self.harness_root = os.path.join(self.root, "harness")
            os.makedirs(self.overlay_root, exist_ok=True)
            os.makedirs(self.harness_root, exist_ok=True)
            target = os.path.join(self.overlay_root, self.relative)
            parent = os.path.dirname(target)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(self.data)
            if self.executable:
                os.chmod(target, 0o700)
            if self.ctx.observer is not None:
                self.ctx.observer("overlay_created",
                                  {"root": self.overlay_root, "entries": 1})
            return self

        def __exit__(self, *_exc):
            shutil.rmtree(self.root, ignore_errors=True)
            if self.root in self.ctx._temp_roots:
                self.ctx._temp_roots.remove(self.root)
            self.ctx.live_temp_artifacts -= 1
            if self.ctx.observer is not None:
                self.ctx.observer("overlay_released", {"root": self.root})
            return False

        @property
        def target(self):
            return os.path.join(self.overlay_root, self.relative)

    def workspace(self, data, relative=None, executable=False):
        relative = relative or (posixpath.basename(self.normalized_path or "")
                                or "candidate")
        return self._Workspace(self, data, relative, executable)

    # -- child processes ---------------------------------------------------
    def child_env(self, root):
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": root,
            "TMPDIR": root,
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            # A child that cannot discover a repository cannot mutate one.
            "GIT_CEILING_DIRECTORIES": root,
            "GIT_DIR": os.path.join(root, ".no-such-git-dir"),
            "GIT_INDEX_FILE": os.path.join(root, ".no-such-index"),
        }
        return env

    def interpreter_argv(self, target):
        if self.detected_kind == KIND_PYTHON:
            return [sys.executable, target]
        if self.detected_kind == KIND_SHELL:
            return [self.shell_binary, target]
        return [target]

    def run(self, argv, cwd=None, env=None):
        if self.observer is not None:
            self.observer("subprocess", {"argv": list(argv), "cwd": cwd})
        try:
            return subprocess.run(
                argv, cwd=cwd, env=env or self.child_env(cwd or
                                                         self.outside_root),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                argv, 124, exc.stdout or b"",
                (exc.stderr or b"") + b"\ntimed out")
        except OSError as exc:
            return subprocess.CompletedProcess(argv, 127, b"",
                                               str(exc).encode("utf-8"))

    # -- composition -------------------------------------------------------
    def compose(self, selection):
        """EVERY composition is counted here, and the cap is enforced here.

        Counting inside the per-check evaluation instead left the baseline
        and full-selection compositions outside the budget, so the declared
        bound could be exceeded by a fixed amount that grows with the number
        of mandatory checks. The counter belongs where the work happens.
        """
        requested = tuple(selection)
        if self.evaluations_performed >= self.evaluation_cap:
            self.cap_reached = True
            return None, EVAL_CAPPED
        self.evaluations_performed += 1
        result = self.composer.compose(set(requested))
        status = _attr(result, "status")
        if status == COMPOSE_NOT_COMPOSABLE:
            return None, _attr(result, "reason") or COMPOSE_NOT_COMPOSABLE
        if status != COMPOSE_COMPOSED:
            return None, "producer returned an unrecognised status %r" % status
        _check_bijection(result, requested)
        data = _attr(result, "bytes")
        if not isinstance(data, (bytes, bytearray)):
            raise ComposerRejected(
                REASON_REGION_GRANULARITY,
                "the producer returned no candidate bytes for the requested "
                "selection")
        data = bytes(data)
        return result, None

    # -- per-check evaluation with a bounded, counted budget ---------------
    def evaluate(self, check, selection):
        """Returns (status, key_multiset, diagnostics). Serial by construction:
        the composed image and any temporary artifact are released before this
        returns, so nothing accumulates across evaluations."""
        key = (check, frozenset(selection))
        if key in self._cache:
            return self._cache[key]
        result, reason = self.compose(selection)
        if result is None and reason == EVAL_CAPPED:
            return EVAL_CAPPED, None, []
        if result is None:
            self.unresolved_count += 1
            self.unresolved_reasons.append(reason)
            outcome = (EVAL_UNRESOLVED, None, [])
            self._cache[key] = outcome
            return outcome
        data = bytes(_attr(result, "bytes"))
        holder = _ImageHolder(data)
        self._live_images.add(holder)
        self.max_live_images = max(self.max_live_images,
                                   len(self._live_images))
        try:
            predicate = (SC1_REGISTRY if check == CHECK_SC1
                         else SC2_REGISTRY).get(self.detected_kind)
            if predicate is None:
                outcome = (EVAL_UNRESOLVED, None, [])
                self._cache[key] = outcome
                return outcome
            try:
                diagnostics = predicate(data, self)
            except _UnresolvedEvaluation as exc:
                self.unresolved_count += 1
                self.unresolved_reasons.append(str(exc))
                outcome = (EVAL_UNRESOLVED, None, [])
                self._cache[key] = outcome
                return outcome
        finally:
            del holder
            del data
        keys = tuple(sorted(d.key for d in diagnostics))
        self.max_diagnostics[check] = max(self.max_diagnostics.get(check, 0),
                                          len(diagnostics))
        outcome = (EVAL_OK, keys, diagnostics)
        self._cache[key] = outcome
        return outcome

    # -- baseline-derived structures ---------------------------------------
    def set_baseline(self, data):
        self._baseline_bytes = data

    def baseline_document_view(self):
        if self._baseline_bytes is None:
            return None
        if self._baseline_view is None:
            self._baseline_view = _document_view(self._baseline_bytes)
        return self._baseline_view

    def required_anchor_set(self):
        """Derived ONCE, from the frozen discovery context, so a candidate
        cannot reclassify itself between witness-search evaluations."""
        if not self._anchor_derived:
            self._anchor_set = self.discovery.required_anchors(
                self.normalized_path)
            self._anchor_derived = True
        return self._anchor_set

    def json_role(self):
        if self._json_role is None:
            self._json_role = self.discovery.json_role(self.normalized_path)
        return self._json_role


class _ImageHolder:
    __slots__ = ("data", "__weakref__")

    def __init__(self, data):
        self.data = data


# ===========================================================================
# The witness search (R9 + the admissibility rule)
# ===========================================================================

def _multiset_difference(left, right):
    remaining = list(right)
    out = []
    for item in left:
        if item in remaining:
            remaining.remove(item)
        else:
            out.append(item)
    return out


def _minimise_for_key(ctx, check, target_key, full_selection):
    """Deletion-based descent in the stable hunk order for ONE diagnostic key.

    Returns (witness, one_minimal, bounded_out). ``one_minimal`` is True only
    once every single-hunk deletion from the final set is KNOWN not to
    reproduce the key -- a cap hit or an unresolved deletion makes the claim
    unprovable, and the claim is then not made.
    """
    witness = list(full_selection)
    bounded_out = False
    progressed = True
    while progressed:
        progressed = False
        for hunk in list(witness):
            trial = [h for h in witness if h != hunk]
            status, keys, _diagnostics = ctx.evaluate(check, trial)
            if status == EVAL_CAPPED:
                return witness, False, True
            if status == EVAL_UNRESOLVED:
                bounded_out = True
                continue
            if target_key in keys:
                witness = trial
                progressed = True
                break
    if bounded_out:
        return witness, False, True
    for hunk in witness:
        trial = [h for h in witness if h != hunk]
        status, keys, _diagnostics = ctx.evaluate(check, trial)
        if status != EVAL_OK:
            return witness, False, True
        if target_key in keys:  # pragma: no cover - descent already excluded
            return witness, False, True
    return witness, True, False


def _is_exposure_only(ctx, check, witness, full_selection, repaired):
    """Exposure has a POSITIVE signature: removing the set RESTORES a key the
    candidate had REPAIRED.

    When the candidate repaired nothing -- which is always the case on a
    passing baseline -- exposure is impossible and no removal evaluation is
    spent. That is what keeps two concurrent claimants who each break one
    thing from both going unnamed: the negative formulation ("removing the set
    does not yield a pass") would silence both, because removing either leaves
    the other's failure standing.
    """
    if not repaired:
        return False, None, EVAL_OK
    remainder = [h for h in full_selection if h not in set(witness)]
    status, keys, _diagnostics = ctx.evaluate(check, remainder)
    if status != EVAL_OK:
        return False, None, status
    restored = [k for k in keys if k in set(repaired)]
    if restored:
        return True, sorted(restored)[0], EVAL_OK
    return False, None, EVAL_OK


def _region_for_hunk(region_index, hunk_id):
    for region in (region_index or {}).values():
        if _attr(region, "hunk_id") == hunk_id:
            return region
    return None


def _witness_entry(region_index, hunk_id):
    region = _region_for_hunk(region_index, hunk_id)
    claimant = _attr(region, "claimant_id") if region is not None else None
    entry = {
        "hunk_id": hunk_id,
        "claimant_id": claimant,
        "baseline_span": list(_attr(region, "baseline_span") or [])
        if region is not None else [],
        "candidate_span": list(_attr(region, "candidate_span") or [])
        if region is not None else [],
    }
    if claimant is None:
        entry["claimant_identity_unavailable"] = True
    return entry


def _locate(diagnostic, region_index):
    """A span LOCATES a diagnostic; it never establishes that the containing
    hunk CAUSED the failure. Containment seeds the search and is reported as
    a location, never as the witness."""
    if diagnostic.check == CHECK_SC2 and diagnostic.span is None:
        return {"location": LOCATION_UNAVAILABLE}
    if diagnostic.span is None:
        return {"location": LOCATION_UNAVAILABLE}
    start = diagnostic.span[0]
    for region in (region_index or {}).values():
        span = _attr(region, "candidate_span")
        if not span:
            continue
        low, high = span[0], span[1]
        if low <= start < high:
            payload = {"location": _attr(region, "hunk_id")}
            if diagnostic.span[1] > high:
                payload["straddles_region_boundary"] = True
            return payload
    return {"location": LOCATION_OUTSIDE_ALL_HUNKS}


# ===========================================================================
# The gate
# ===========================================================================

def _record_template(evaluation_cap=DEFAULT_EVALUATION_CAP, discovery=None):
    """The record's top-level shape, declared in ONE place.

    The shape is CLOSED: ``RECORD_FIELDS`` is derived from this template, and
    the criteria assert that an emitted record carries exactly these keys.
    A closed shape is how "the gate has no authority to pick a winner, drop a
    hunk or reorder claimants" is checkable rather than merely promised --
    there is nowhere for an instruction field to appear.
    """
    return {
        "schema": SCHEMA_ID,
        "gate_pass": None,
        "soundness_not_asserted": True,
        "reason": None,
        "identity": None,
        "kind_detection": None,
        "checks": [],
        "records": [],
        "unasserted_checks": [],
        "controls": {"empty_selection": None, "per_claimant": []},
        "evaluations_performed": 0,
        "evaluation_cap": evaluation_cap,
        "cap_reached": False,
        "unresolved_count": 0,
        "unresolved_reason": None,
        "discovery_method": (discovery or NullDiscovery()).method,
        "smoke": None,
        "notes": {},
        "resource_profile": {},
        "gate_coverage_claim": GATE_COVERAGE_CLAIM,
    }


RECORD_FIELDS = tuple(sorted(_record_template()))


def evaluate(composer, discovery=None, evaluation_cap=DEFAULT_EVALUATION_CAP,
             timeout=DEFAULT_TIMEOUT_SECONDS, observer=None,
             shell_binary="bash", interpreter_contract=None):
    """Run both mandatory checks against the combined candidate image and
    return one record. Emits; never lands, never refuses a route, never
    mutates an index or a working tree.
    """
    ctx = _Context(composer, discovery, evaluation_cap, timeout, observer,
                   shell_binary)
    record = _record_template(evaluation_cap, discovery)

    if composer is None:
        record["reason"] = REASON_NO_CANDIDATE_IMAGE
        return _finish(record, ctx)

    try:
        hunks = list(composer.hunk_ids())
    except Exception:
        hunks = list(getattr(composer, "hunk_ids", ()) or ())
    full_selection = tuple(hunks)

    try:
        result, reason = ctx.compose(full_selection)
    except ComposerRejected as exc:
        record["reason"] = exc.reason
        record["notes"]["producer_detail"] = exc.detail
        return _finish(record, ctx)
    if result is None:
        record["reason"] = (REASON_UNRESOLVED_EVALUATION if reason == EVAL_CAPPED
                            else REASON_NO_CANDIDATE_IMAGE)
        record["notes"]["producer_detail"] = reason
        return _finish(record, ctx)

    data = bytes(_attr(result, "bytes"))
    region_index = _attr(result, "region_index")
    identity_half = _attr(result, "identity") or {}
    if _attr(identity_half, "content_sha256") is not None:
        record["reason"] = REASON_COMPOSER_SUPPLIED_DIGEST
        record["notes"]["producer_detail"] = (
            "a digest the gate did not compute over the bytes it actually "
            "validated cannot bind a verdict to an object")
        return _finish(record, ctx)

    ctx.normalized_path = normalize_path(_attr(identity_half, "path")
                                         or _attr(result, "path"))
    ctx.content_sha256 = hashlib.sha256(data).hexdigest()

    role = ctx.discovery.invocation_role(ctx.normalized_path)
    kind_detection = detect_kind(ctx.normalized_path, data, role,
                                 interpreter_contract)
    record["kind_detection"] = kind_detection
    ctx.detected_kind = kind_detection["selected"]

    git_mode = _attr(identity_half, "mode")
    if git_mode is None:
        git_mode = _attr(result, "mode")
    record["identity"] = {
        "normalized_path": ctx.normalized_path,
        "content_sha256": ctx.content_sha256,
        "git_mode": git_mode,
        "detected_kind": ctx.detected_kind,
        "validation_context_digest": None,
    }

    if ctx.detected_kind is None:
        record["reason"] = kind_detection["reason"]
        record["identity"]["validation_context_digest"] = \
            _context_digest(ctx, record)
        return _finish(record, ctx)

    # Baseline control -- the empty selection. Required: without it an
    # already-broken file would be blamed on whichever claimant was present.
    baseline_result, baseline_reason = None, None
    try:
        baseline_result, baseline_reason = ctx.compose(())
    except ComposerRejected as exc:
        record["reason"] = exc.reason
        record["notes"]["producer_detail"] = exc.detail
        record["identity"]["validation_context_digest"] = \
            _context_digest(ctx, record)
        return _finish(record, ctx)
    if baseline_result is not None:
        ctx.set_baseline(bytes(_attr(baseline_result, "bytes")))
    else:
        record["notes"]["baseline_unavailable"] = baseline_reason

    # The SC-2 entry form is discovered ONCE, from the candidate, and frozen
    # for every evaluation the witness search performs -- a predicate that
    # could change between sub-combinations would make the minimal set
    # meaningless. It is part of the validation context, so the digest below
    # binds the verdict to the form that actually ran.
    if ctx.detected_kind in (KIND_PYTHON, KIND_SHELL):
        ctx.smoke_plan = plan_smoke_form(data, ctx)
    record["smoke"] = ctx.smoke_plan

    record["identity"]["validation_context_digest"] = _context_digest(ctx,
                                                                      record)

    controls = {"empty_selection": {}, "per_claimant": []}
    for check in MANDATORY_CHECKS:
        check_record, failure_record = _run_check(
            ctx, check, full_selection, region_index, controls)
        record["checks"].append(check_record)
        if failure_record is not None:
            record["records"].append(failure_record)
        if check_record["result"] == RESULT_NOT_ASSERTED:
            record["unasserted_checks"].append({
                "check": check,
                "reason": check_record["reason"],
                "detail": check_record.get("detail"),
            })
    controls["per_claimant"] = _per_claimant_controls(ctx, region_index,
                                                      full_selection)
    record["controls"] = controls
    record["notes"].update(ctx.notes)
    return _finish(record, ctx)


def _context_digest(ctx, record):
    """Over the gate's OWN derived SC-2 context. A verdict issued against a
    different context is stale, so the context is part of the identity."""
    payload = {
        "required_anchor_set": sorted(ctx.required_anchor_set() or [])
        if ctx.detected_kind == KIND_MARKDOWN else None,
        "json_role": ctx.json_role()[0] if ctx.detected_kind == KIND_JSON
        else None,
        "precedence_rule": (record["kind_detection"] or {}).get(
            "precedence_rule"),
        "invocation_role": (record["kind_detection"] or {}).get(
            "invocation_role"),
        "sc2_predicate": SC2_PREDICATE_NAME.get(ctx.detected_kind),
        "discovered_entry_form": (ctx.smoke_plan or {}).get("form"),
        "discovery_method": ctx.discovery.method,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _run_check(ctx, check, full_selection, region_index, controls):
    predicate_available = (SC1_REGISTRY if check == CHECK_SC1
                           else SC2_REGISTRY).get(ctx.detected_kind)
    base = {"check": check, "detected_kind": ctx.detected_kind,
            "predicate": SC2_PREDICATE_NAME.get(ctx.detected_kind)
            if check == CHECK_SC2 else "language_syntax_check",
            "first_error_only_producer": True}
    if predicate_available is None:
        base.update({"result": RESULT_NOT_ASSERTED,
                     "reason": REASON_NO_DECLARED_PARSER_FOR_KIND,
                     "detection_method": "extension and shebang signals, "
                                         "invocation role from discovery"})
        return base, None

    try:
        baseline_status, baseline_keys, baseline_diagnostics = ctx.evaluate(
            check, ())
        candidate_status, candidate_keys, candidate_diagnostics = ctx.evaluate(
            check, full_selection)
    except NotAsserted as exc:
        base.update({"result": RESULT_NOT_ASSERTED, "reason": exc.reason,
                     "detail": exc.detail})
        base.update(exc.extra)
        return base, None
    except ComposerRejected as exc:
        base.update({"result": RESULT_NOT_ASSERTED, "reason": exc.reason,
                     "detail": exc.detail})
        return base, None

    controls["empty_selection"] = controls.get("empty_selection") or {}
    controls["empty_selection"][check] = {
        "status": baseline_status,
        "diagnostics": [d.as_dict() for d in baseline_diagnostics],
    }

    if candidate_status != EVAL_OK:
        base.update({"result": RESULT_NOT_ASSERTED,
                     "reason": REASON_UNRESOLVED_EVALUATION,
                     "detail": "the combined selection could not be evaluated"})
        return base, None

    base["first_error_only_producer"] = ctx.first_error_only(check)
    baseline_failed = bool(baseline_keys) if baseline_status == EVAL_OK \
        else None
    if not candidate_keys:
        base.update({"result": RESULT_PASS})
        if baseline_failed:
            base["baseline_unsound_repaired_by_candidate"] = True
            base["preexisting_unsound"] = True
            base["baseline_diagnostic"] = [d.as_dict()
                                           for d in baseline_diagnostics]
        return base, None

    base.update({"result": RESULT_FAIL})
    if baseline_failed:
        base["preexisting_unsound"] = True
        base["baseline_diagnostic"] = [d.as_dict()
                                       for d in baseline_diagnostics]

    residual = _multiset_difference(candidate_keys, baseline_keys or ())
    repaired = _multiset_difference(baseline_keys or (), candidate_keys)
    failure = {
        "check": check,
        "detected_kind": ctx.detected_kind,
        "diagnostic": [d.as_dict() for d in candidate_diagnostics],
        "locations": [dict({"diagnostic_class": d.diagnostic_class},
                           **_locate(d, region_index))
                      for d in candidate_diagnostics],
        "preexisting_unsound": bool(baseline_failed),
        "baseline_diagnostic": [d.as_dict() for d in baseline_diagnostics],
        "residual_keys": [list(k) for k in residual],
        "repaired_keys": [list(k) for k in repaired],
        "first_error_only_producer": ctx.first_error_only(check),
        "witness_hunks": [],
        "unmasking_witness": [],
        "witness_is_1_minimal": True,
        "evaluations_performed": 0,
        "evaluation_cap": ctx.evaluation_cap,
        "cap_reached": False,
        "attribution": None,
        "attribution_reason": None,
    }

    if not residual:
        failure["attribution"] = ATTRIBUTION_NO_COMBINATION
        failure["attribution_reason"] = ATTRIBUTION_REASON_NO_RESIDUAL
        # Sameness was decided on the diagnostic KEY, whose normalisation is
        # location-only by design -- that is what stops every insertion from
        # reading as a regression. The cost is that two structurally distinct
        # defects producing the identical message collapse to one key, and
        # then "this failure pre-exists your edits" is true of the KEY while
        # the occurrence may have moved. The gate knows the spans, so it says
        # so rather than letting the reader over-read the sentinel.
        baseline_spans = sorted(tuple(d.span) for d in baseline_diagnostics
                                if d.span is not None)
        candidate_spans = sorted(tuple(d.span) for d in candidate_diagnostics
                                 if d.span is not None)
        failure["same_key_same_location"] = baseline_spans == candidate_spans
        if not failure["same_key_same_location"]:
            failure["attribution_qualifier"] = (
                "the residual is empty by diagnostic key, but the occurrence "
                "moved: location-only normalisation cannot distinguish two "
                "defects that produce the identical message")
            failure["baseline_spans"] = [list(s) for s in baseline_spans]
            failure["candidate_spans"] = [list(s) for s in candidate_spans]
        failure["evaluations_performed"] = ctx.evaluations_performed
        failure["cap_reached"] = ctx.cap_reached
        base["attribution"] = failure["attribution"]
        return base, failure

    before = ctx.evaluations_performed
    bounded_out = False
    one_minimal = True
    for target_key in residual:
        witness, minimal, hit_bound = _minimise_for_key(
            ctx, check, target_key, full_selection)
        one_minimal = one_minimal and minimal
        bounded_out = bounded_out or hit_bound
        exposure, restored, status = _is_exposure_only(
            ctx, check, witness, full_selection, repaired)
        entry_hunks = [_witness_entry(region_index, h) for h in witness]
        if status != EVAL_OK:
            bounded_out = True
            failure.setdefault("undecided_exposure", []).append({
                "target_key": list(target_key),
                "hunks": entry_hunks,
                "status": status,
            })
            continue
        if exposure:
            failure["unmasking_witness"].append({
                "hunks": entry_hunks,
                "exposed_diagnostic": list(target_key),
                "restored_baseline_diagnostic": list(restored),
            })
            continue
        failure["witness_hunks"].append({
            "target_key": list(target_key),
            "hunks": entry_hunks,
            "witness_is_1_minimal": minimal,
        })

    failure["witness_is_1_minimal"] = one_minimal and not bounded_out
    failure["evaluations_performed"] = ctx.evaluations_performed - before
    failure["cap_reached"] = ctx.cap_reached
    failure["witness_hunks"].sort(key=lambda w: (
        [h["hunk_id"] for h in w["hunks"]], w["target_key"]))
    failure["unmasking_witness"].sort(key=lambda w: (
        [h["hunk_id"] for h in w["hunks"]], w["exposed_diagnostic"]))

    # Re-measured after the search: an evaluation the search performed may
    # have shown the producer returning more than one diagnostic, which
    # settles the question the baseline/candidate pair alone could not.
    failure["first_error_only_producer"] = ctx.first_error_only(check)
    base["first_error_only_producer"] = failure["first_error_only_producer"]

    if failure["witness_hunks"]:
        failure["attribution"] = None
        failure["attribution_reason"] = None
    elif failure["unmasking_witness"]:
        failure["attribution"] = ATTRIBUTION_MASKED_PREEXISTING
        failure["attribution_reason"] = ATTRIBUTION_REASON_EXPOSED
    else:
        # Truthful on a PASSING baseline too: it names the search's own
        # termination, not a property of the baseline. The two older sentinels
        # both assert something about the baseline and would be false here.
        failure["attribution"] = ATTRIBUTION_NO_ADMISSIBLE_WITNESS
        failure["attribution_reason"] = ATTRIBUTION_REASON_SEARCH_BOUNDED_OUT
        failure["retained_failing_combination"] = [
            _witness_entry(region_index, h) for h in full_selection]

    base["attribution"] = failure["attribution"]
    return base, failure


def _per_claimant_controls(ctx, region_index, full_selection):
    by_claimant = {}
    for region in (region_index or {}).values():
        claimant = _attr(region, "claimant_id")
        by_claimant.setdefault(claimant, []).append(_attr(region, "hunk_id"))
    out = []
    for claimant in sorted(by_claimant, key=lambda c: (c is None, str(c))):
        selection = [h for h in full_selection if h in set(by_claimant[claimant])]
        entry = {"claimant_id": claimant,
                 "claimant_identity_unavailable": claimant is None,
                 "hunk_ids": sorted(by_claimant[claimant], key=repr),
                 "results": {}}
        for check in MANDATORY_CHECKS:
            try:
                status, keys, _diagnostics = ctx.evaluate(check, selection)
            except (NotAsserted, ComposerRejected) as exc:
                entry["results"][check] = {"status": RESULT_NOT_ASSERTED,
                                           "reason": getattr(exc, "reason",
                                                             None)}
                continue
            if status != EVAL_OK:
                entry["results"][check] = {"status": status}
            else:
                entry["results"][check] = {
                    "status": RESULT_FAIL if keys else RESULT_PASS,
                    "diagnostic_keys": [list(k) for k in keys],
                }
        out.append(entry)
    return out


def _finish(record, ctx):
    """R7 aggregation, evaluated in ONE place and in ONE order.

    Failure dominates non-assertion: a demonstrated failure is a stronger,
    more actionable fact than an unasserted one, and collapsing it into
    ``None`` would hide a known defect behind a coverage gap. Both are
    retained in the record, so the precedence loses nothing.
    """
    record["evaluations_performed"] = ctx.evaluations_performed
    record["cap_reached"] = ctx.cap_reached
    record["unresolved_count"] = ctx.unresolved_count
    record["unresolved_reason"] = (ctx.unresolved_reasons[0]
                                   if ctx.unresolved_reasons else None)
    record["resource_profile"] = {
        "max_live_composed_images": max(ctx.max_live_images, 0),
        "max_live_temp_artifacts": ctx.max_live_temp_artifacts,
        "serial_evaluation": True,
        "retained_across_evaluations": ["scalar_results", "selection_listing"],
        "duplicated_checkout": False,
    }
    results = [c.get("result") for c in record["checks"]]
    if any(r == RESULT_FAIL for r in results):
        record["gate_pass"] = False
    elif (record["reason"] is not None
            or len(record["checks"]) < len(MANDATORY_CHECKS)
            or any(r == RESULT_NOT_ASSERTED for r in results)
            or record["unresolved_count"] > 0):
        record["gate_pass"] = None
    else:
        record["gate_pass"] = True
    record["soundness_not_asserted"] = record["gate_pass"] is None
    if record["reason"] is None and record["gate_pass"] is None:
        if record["unasserted_checks"]:
            record["reason"] = record["unasserted_checks"][0]["reason"]
        elif record["unresolved_count"]:
            record["reason"] = REASON_UNRESOLVED_EVALUATION
    if record["reason"] is not None and not record["checks"]:
        # An invocation that never reached a per-check evaluation still owes
        # one enumerated reason PER MANDATORY CHECK. Leaving the list empty
        # would make "no check was asserted" indistinguishable from "no check
        # was required", which is the shape R7 forbids.
        record["unasserted_checks"] = [
            {"check": check, "reason": record["reason"],
             "detail": record["notes"].get("producer_detail")}
            for check in MANDATORY_CHECKS]
    record["unasserted_checks"].sort(key=lambda e: (e["check"], e["reason"]))
    return record


# ===========================================================================
# Identity binding (R10) -- comparison against the OBJECT, never a re-read
# ===========================================================================

def verify_identity(record, landing_object):
    """Compare the identity of the EXACT object being handed to landing with
    the identity the verdict was issued for.

    A re-read of the mutable path is not an acceptable comparison input: that
    is the time-of-check/time-of-use gap this comparison exists to close, and
    no lock around repository operations closes it.
    """
    issued = (record or {}).get("identity")
    if issued is None:
        return REASON_IDENTITY_MISMATCH
    data = _attr(landing_object, "bytes")
    if data is None:
        return REASON_IDENTITY_MISMATCH
    actual = {
        "normalized_path": normalize_path(_attr(landing_object, "path")),
        "content_sha256": hashlib.sha256(bytes(data)).hexdigest(),
        "git_mode": _attr(landing_object, "mode"),
    }
    for field, value in actual.items():
        if issued.get(field) != value:
            return REASON_IDENTITY_MISMATCH
    return None


# ===========================================================================
# Standalone offline entry point
# ===========================================================================

def _cli(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the two mandatory soundness checks against a "
                    "candidate image supplied by any producer.")
    parser.add_argument("--candidate", required=True,
                        help="file holding the combined candidate bytes")
    parser.add_argument("--path", required=True,
                        help="repo-relative path the candidate represents")
    parser.add_argument("--mode", default="100644")
    parser.add_argument("--baseline", help="file holding the baseline bytes")
    parser.add_argument("--git-root",
                        help="enable tracked-set discovery rooted here")
    parser.add_argument("--evaluation-cap", type=int,
                        default=DEFAULT_EVALUATION_CAP)
    parser.add_argument("--explain", action="store_true",
                        help="print every evaluation the search performed")
    args = parser.parse_args(argv)

    with open(args.candidate, "rb") as handle:
        candidate = handle.read()
    baseline = b""
    if args.baseline:
        with open(args.baseline, "rb") as handle:
            baseline = handle.read()

    composer = WholeFileComposer(args.path, candidate, baseline, args.mode)
    discovery = (TrackedSetDiscovery(args.git_root) if args.git_root
                 else NullDiscovery())
    record = evaluate(composer, discovery=discovery,
                      evaluation_cap=args.evaluation_cap)
    if not args.explain:
        record.pop("controls", None)
    json.dump(record, sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return 0 if record["gate_pass"] else (1 if record["gate_pass"] is False
                                          else 2)


class WholeFileComposer:
    """The degenerate D1 producer: one hunk, the whole file.

    Used by the standalone entry point and by the whole-file adoption seam,
    where the candidate image IS the file and there is exactly one atomic
    region to attribute to.
    """

    def __init__(self, path, candidate, baseline=b"", mode="100644",
                 claimant_id=None, hunk_id="whole-file"):
        self.path = path
        self.mode = mode
        self._candidate = candidate
        self._baseline = baseline
        self._claimant_id = claimant_id
        self._hunk_id = hunk_id

    def hunk_ids(self):
        return [self._hunk_id]

    def compose(self, selection):
        selected = self._hunk_id in set(selection)
        data = self._candidate if selected else self._baseline
        region_index = {}
        if selected:
            region_index[self._hunk_id] = {
                "claimant_id": self._claimant_id,
                "hunk_id": self._hunk_id,
                "baseline_span": [0, len(self._baseline)],
                "candidate_span": [0, len(data)],
            }
        return {
            "status": COMPOSE_COMPOSED,
            "bytes": data,
            "path": self.path,
            "mode": self.mode,
            "region_index": region_index,
            "coordinate_map": {self._hunk_id: [0, len(data)]} if selected
            else {},
            "identity": {"path": self.path, "mode": self.mode},
        }


class SliceComposer:
    """A D1 producer over ORDERED, PAIRWISE-DISJOINT baseline slices.

    ``slices`` is ``[(hunk_id, claimant_id, baseline_start, baseline_end,
    produced_bytes)]``. One slice is one atomic hunk, so ``region -> hunk_id``
    is a bijection by construction and the witness search can select any
    subset. Composition splices the selected slices into the immutable
    baseline in baseline order -- never onto an already-mutated buffer, which
    silently corrupts an image while every individual span stays well-formed.

    This is what keeps the refusal HUNK-level on a live route rather than
    degenerating to "the whole file", which is the defect the gate exists to
    remove.
    """

    def __init__(self, path, baseline, slices, mode="100644"):
        self.path = path
        self.mode = mode
        self.baseline = baseline
        self.slices = sorted(slices, key=lambda s: (s[2], s[3], str(s[0])))

    def hunk_ids(self):
        return [item[0] for item in self.slices]

    def compose(self, selection):
        selection = set(selection)
        pieces = []
        regions = {}
        cursor = 0
        produced_at = 0
        for hunk_id, claimant, start, end, produced in self.slices:
            if hunk_id not in selection:
                continue
            if start < cursor:
                return {"status": COMPOSE_NOT_COMPOSABLE,
                        "reason": "two selected slices overlap on the "
                                  "baseline, so their order is not determined"}
            head = self.baseline[cursor:start]
            pieces.append(head)
            produced_at += len(head)
            regions[hunk_id] = {
                "claimant_id": claimant,
                "hunk_id": hunk_id,
                "baseline_span": [start, end],
                "candidate_span": [produced_at, produced_at + len(produced)],
            }
            pieces.append(produced)
            produced_at += len(produced)
            cursor = end
        pieces.append(self.baseline[cursor:])
        data = b"".join(pieces)
        return {"status": COMPOSE_COMPOSED, "bytes": data, "path": self.path,
                "mode": self.mode, "region_index": regions,
                "coordinate_map": {k: v["candidate_span"]
                                   for k, v in regions.items()},
                "identity": {"path": self.path, "mode": self.mode}}


def describe_refusal(record):
    """A locatable refusal line: WHICH combination of hunks caused WHICH
    check to fail, never "this file was excluded" with no reason.

    Returns ``None`` when the gate did not DEMONSTRATE a failure. A
    non-assertion is not a refusal: the gate issues no authorization for it,
    and choosing refusal versus deferral there belongs to the landing owner.
    """
    if (record or {}).get("gate_pass") is not False:
        return None
    parts = []
    for failure in record.get("records", []):
        if failure.get("witness_hunks"):
            for witness in failure["witness_hunks"]:
                hunks = ", ".join(str(h["hunk_id"]) for h in witness["hunks"])
                parts.append("%s failed; the combination {%s} reproduces it "
                             "and no proper subset does"
                             % (failure["check"], hunks))
        elif failure.get("attribution"):
            detail = "%s failed; %s (%s)" % (failure["check"],
                                             failure["attribution"],
                                             failure["attribution_reason"])
            if failure.get("unmasking_witness"):
                uncovered = ", ".join(
                    str(h["hunk_id"])
                    for witness in failure["unmasking_witness"]
                    for h in witness["hunks"])
                detail += ("; the recorded edit that merely uncovered it: {%s}"
                           % uncovered)
            parts.append(detail)
        else:
            parts.append("%s failed" % failure["check"])
        raw = failure.get("diagnostic") or []
        if raw:
            parts[-1] += " -- %s" % raw[0].get("message_normalised")
    return "; ".join(parts) if parts else "a mandatory soundness check failed"


def screen_landing(path, image, mode, slices=None, baseline=b"",
                   git_root=None, claimant_id=None, stream=None):
    """CONSUMPTION helper for a landing route. Not the gate itself.

    Returns a refusal string when the gate DEMONSTRATED a failure, else
    ``None``. The disposition of a non-assertion is deliberately NOT a
    refusal here: ``gate_pass: null`` authorizes nothing, but turning it into
    a refusal would block a claimant whose own work is sound merely because
    no consumer contract could be discovered -- which would regress the
    requirement that two sessions can always land their own work. A
    non-assertion is therefore REPORTED, visibly, and left to the landing
    owner to decide.

    An internal fault in the gate is treated as a non-assertion, never as a
    silent pass and never as a refusal: a new component must not be able to
    block a landing by crashing, and must not be able to authorize one
    either.
    """
    stream = stream if stream is not None else sys.stderr
    try:
        if slices:
            composer = SliceComposer(path, baseline, slices, mode)
            rebuilt = composer.compose(set(composer.hunk_ids()))
            if rebuilt.get("bytes") != image:
                composer = WholeFileComposer(path, image, baseline, mode,
                                             claimant_id=claimant_id)
                stream.write(
                    "soundness-gate: the hunk decomposition does not "
                    "reassemble the candidate image for %s; attribution "
                    "degrades to whole-file for this landing\n" % path)
        else:
            composer = WholeFileComposer(path, image, baseline, mode,
                                         claimant_id=claimant_id)
        discovery = (TrackedSetDiscovery(git_root) if git_root
                     else NullDiscovery())
        record = evaluate(composer, discovery=discovery)
    except Exception as exc:  # the gate must never break a landing by faulting
        stream.write("soundness-gate: not asserted for %s -- the gate itself "
                     "faulted (%s)\n" % (path, type(exc).__name__))
        return None
    refusal = describe_refusal(record)
    if refusal is not None:
        return "soundness gate: %s" % refusal
    if record.get("gate_pass") is not True:
        # Repo-relative path and the reason code only. Absolute paths and
        # free text are deliberately kept out of this line: it is written on
        # ordinary landings, and other consumers assert on this stream.
        stream.write("soundness-gate: not asserted for %s -- %s\n"
                     % (path, record.get("reason")))
    return None


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(_cli())
