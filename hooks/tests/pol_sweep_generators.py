"""Rule-generated adversarial and benign corpora for the LANE-POL removal policy.

WHY THIS FILE IS THE DELIVERABLE, NOT ITS OUTPUT (AC-R02-13). Two consecutive
implementations passed a pinned 436-row corpus at 0 mismatches while a sweep
over the SAME dimensions leaked 76.1%. A fixed corpus cannot observe a leak that
MUTATES between iterations — "absence authorizes" became "membership
authorizes" without a single corpus row changing verdict. Every deny-side
population here is therefore computed from a RULE at run time: the installed
program set comes from PATH, the option grammar comes from each member's own
declared option model, and the shell-form corpus is a cross product over six
orthogonal dimensions. Adding a dimension value changes the population without
touching a single assertion.

ZERO EXECUTION. Every string produced here is DATA. It is handed to
``bash_execution_boundary.analyze()`` in-process, or to the hook as JSON on
stdin. Nothing in this module executes, expands, evals, or shells out a
generated command. The only processes the harness spawns are the hook itself
and pytest.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import bash_execution_boundary as B  # noqa: E402  (path set above)

TARGET = "qa-target"

DEGRADED_PREDICATE_FILE = os.path.join(
    REPO_ROOT, "hooks", "lib", "pol_degraded_removal_reference.ere")


# ---------------------------------------------------------------------------
# The degraded predicate is READ, never re-implemented (AC-R02-10).
# ---------------------------------------------------------------------------

def degraded_removal_reference_pattern():
    """The one definition the hook executes. A copy here would be worthless:
    the invariant it supports is precisely that the two sides cannot drift."""
    with open(DEGRADED_PREDICATE_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    raise AssertionError("degraded removal-reference predicate is empty: "
                         + DEGRADED_PREDICATE_FILE)


def degraded_denies_removal_reference(command):
    return re.search(degraded_removal_reference_pattern(), command) is not None


# ---------------------------------------------------------------------------
# Runtime-derived populations
# ---------------------------------------------------------------------------

def installed_programs():
    """Every executable basename on PATH, enumerated NOW.

    Hard-coding this list (or its size) would reintroduce exactly the corpus
    binding AC-R02-11 exists to remove: a binary installed after this cycle
    must be covered without anyone editing a test.
    """
    names = set()
    for d in os.environ.get("PATH", "/usr/bin:/bin").split(":"):
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for nm in entries:
            p = os.path.join(d, nm)
            try:
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    names.add(nm)
            except OSError:
                continue
    return sorted(names)


def installed_wrappers():
    """Installed programs this analyzer models as prefix wrappers, for nesting."""
    on_path = set(installed_programs())
    out = [w for w in ("env", "nohup", "setsid", "nice", "ionice", "stdbuf",
                       "eatmydata", "strace", "taskset")
           if w in on_path and B.WRAPPERS.get(w) is not None]
    return out or ["env"]


# ---------------------------------------------------------------------------
# AC-R02-11 — installed-program argv sweep
# ---------------------------------------------------------------------------

def installed_program_sweep():
    """`<P> /bin/rm -rf <target>` for every P on PATH. Never executed."""
    return ["%s /bin/rm -rf %s" % (p, TARGET) for p in installed_programs()]


def installed_program_counterweight():
    """`man <P>` / `which <P>` for every P: the stricter default must not be
    reachable by denying ordinary lookups."""
    out = []
    for p in installed_programs():
        out.append("man %s" % p)
        out.append("which %s" % p)
    return out


# ---------------------------------------------------------------------------
# AC-R02-12 — positional discrimination over the authorizing table
# ---------------------------------------------------------------------------

# Probe tokens used as UNDECLARED options. A token the member's model declares
# BOOLEAN is not an option-value position at all (the removal front end after
# `ls -X` is an operand), so it is filtered out per member — otherwise the two
# halves of AC-R02-12 would contradict each other.
GENERIC_OPTION_PROBES = ("-X", "-Z", "-Q", "-Y", "-K",
                         "--opt", "--program", "--use", "--via")


def option_grammar_for(member):
    """Exec options first, then generic probes MINUS anything this member
    declares boolean.

    The filter is not a loophole, it is what keeps the criterion coherent:
    `ls -X` is a real boolean (sort by extension) and `id --use` is an
    unambiguous abbreviation of the boolean `--user`, so in `ls -X /bin/rm` the
    removal front end sits in OPERAND position — the exact placement the other
    half of AC-R02-12 requires to ALLOW. A probe token is only an option-value
    position when the member does not declare it valueless.
    """
    model = B.INERT_ARGV_CONSUMERS[member]

    def is_declared_bool(tok):
        if tok in model["bool"]:
            return True
        if tok.startswith("--"):
            return B._resolve_ic_long(tok, model) in model["bool"]
        return all(("-" + ch) in model["bool"] for ch in tok[1:])

    tokens = sorted(model["exec"])
    tokens += [t for t in GENERIC_OPTION_PROBES if not is_declared_bool(t)]
    return tokens


# The VALUE ALPHABET. Iteration 3 measured 0/2520 option-value allows using
# only BARE removal heads, and shipped a hook that allowed 993/1635 the moment
# QA substituted COMMAND-LINE-SHAPED values: the attached branches tested a
# token predicate, the separated branches a payload predicate, and the two
# disagree on exactly these strings. A value alphabet that cannot express the
# difference cannot see the defect, so it is generated across both shapes.
def _canonical_removal_command():
    """The one base command the COMMAND-POSITION dimensions are applied to."""
    return "/bin/rm -rf %s" % TARGET


def _head_and_flag_values():
    """Dimension 1-2: how the removal front end and its flags are written."""
    heads = ("/bin/rm", "rm", "unlink", "/bin/r?")
    flagsets = ("", "-rf", "-r -f", "--recursive --force")
    out = []
    for head in heads:
        for flags in flagsets:
            label = "head_%s__flags_%s" % (head, flags or "none")
            out.append((label, head if not flags
                        else "%s %s %s" % (head, flags, TARGET)))
    return out


def _wrapper_prefix_values():
    """Dimension 3: the removal command behind an INSTALLED EXEC WRAPPER.

    The wrapper names are read out of the analyzer's OWN wrapper table and
    filtered by PATH at run time, so a wrapper the analyzer learns about — or a
    binary the host gains — enters this alphabet without anyone editing it.
    This dimension is why the alphabet stopped being a checked-in tuple: QA
    measured 19641/24032 option-value probes ALLOWED because the top-level walk
    knew this exact set while the option-value predicate knew only shells and
    interpreters, and dev's own guard could not see it because the guard
    iterated dev's own ten literal values.
    """
    on_path = set(installed_programs())
    base = _canonical_removal_command()
    out = []
    for name in sorted(B.WRAPPERS):
        if B.WRAPPERS[name] is None or name not in on_path:
            continue
        spec, nops = B.WRAPPERS[name]
        lead = " ".join(["1"] * nops)
        out.append(("wrapper_%s" % name,
                    " ".join(x for x in (name, lead, base) if x)))
    return out


def _command_position_values():
    """Dimension 4: the removal front end is NOT the first word.

    Includes the stated V5/V6/V7 shapes and the shell keyword / group /
    leading-redirection forms, all built from the same base command.
    """
    base = _canonical_removal_command()
    return [("separator", "x; " + base),
            ("control_operator", "true && " + base),
            ("assignment_prefix", "LC_ALL=C " + base),
            ("keyword_if", "if true; then %s; fi" % base),
            ("group", "{ %s; }" % base),
            ("leading_redirection", "> out " + base)]


def _nesting_values(max_depth=3):
    """Dimension 5: nesting depth, generated rather than enumerated.

    Iteration 4 patched exactly the ONE nested shape AC-R02-12's V8 names, so
    depth 1 denied while depth 2 (`sh -c 'sh -c /bin/rm'`) allowed. Depth is a
    dimension here, so no single depth can be the one that was patched.
    """
    out = []
    payload = _canonical_removal_command()
    for depth in range(1, max_depth + 1):
        payload = "sh -c %s" % _quote_value(payload)
        out.append(("nested_depth_%d" % depth, payload))
    return out


def _tokenization_values():
    """Dimension 6: forms whose CANONICAL tokenization differs from a shell's.

    `x;/bin/rm${IFS}-rf${IFS}qa-target` has no whitespace at all, so a value
    predicate that splits on whitespace reads it as one program reference while
    a shell reads it as two commands and runs the second.
    """
    base = _canonical_removal_command()
    return [("ifs_joined", "x;" + base.replace(" ", "${IFS}")),
            ("separator_unspaced", "x;" + base),
            ("tab_separated", base.replace(" ", "\t")),
            ("in_value_comma", "x,/bin/rm"),
            ("in_value_colon", "x:/bin/rm")]


def _combined_dimension_values():
    """AC-R02-12 revision 4: the alphabet CLOSED UNDER COMPOSITION.

    A rule that applies its dimensions ONE AT A TIME is still an enumeration of
    single shapes — dev disclosed exactly that about the six dimensions above,
    and the composed shape (a wrapper prefix INSIDE a nested shell, or a
    wrapper form whose separators are rewritten) is the class this lane has
    been rejected on twice. Two dimension PAIRS are required:

      wrapper x nesting       -- every wrapper value at inner-shell depth 1 and 2
      wrapper x tokenization  -- every wrapper value in ${IFS}-joined and
                                 unspaced-separator form

    The wrapper dimension is itself derived from the analyzer's own table
    filtered by PATH, so a host with no installed exec wrapper produces an
    EMPTY family here and ``combined_dimension_report`` reports 0 rather than
    silently sweeping nothing.
    """
    out = []
    for label, value in _wrapper_prefix_values():
        name = label[len("wrapper_"):]
        payload = value
        for depth in (1, 2):
            payload = "sh -c %s" % _quote_value(payload)
            out.append(("wrapper_%s__nested_depth_%d" % (name, depth), payload))
        out.append(("wrapper_%s__ifs_joined" % name,
                    "x;" + value.replace(" ", "${IFS}")))
        out.append(("wrapper_%s__separator_unspaced" % name, "x;" + value))
    return out


def generated_option_values():
    """THE option-VALUE alphabet, computed from six dimensions at run time.

    AC-R02-12's GIVEN states V1..V8 as a FLOOR ("must contain at least"), and
    those eight are produced by the dimensions below rather than transcribed —
    ``test_ac_r02_12_value_alphabet_covers_the_stated_v1_v8`` proves it. The
    alphabet is generated because a checked-in tuple can only ever exhibit the
    leak its author already knew about: dev's iteration-4 uniformity guard
    reported 0/9720 divergent over its own ten values while QA measured
    543/3888 divergent over a wider one.
    """
    out = []
    out += _head_and_flag_values()
    out += _wrapper_prefix_values()
    out += _command_position_values()
    out += _nesting_values()
    out += _tokenization_values()
    out += _combined_dimension_values()
    seen, uniq = set(), []
    for label, value in out:
        if value in seen:
            continue
        seen.add(value)
        uniq.append((label, value))
    return tuple(uniq)

# AC-R02-12 revision 3 option-TOKEN classes. Each member's grammar draws from
# all four, and the THEN clause gives them different obligations: (a) and (d)
# must DENY, (c) must ALLOW, (b) hands its follower to the operand counterweight.
TOKEN_CLASS_EXEC = "exec_declared"
TOKEN_CLASS_BOOL = "bool_declared"
TOKEN_CLASS_DATA = "data_declared"
TOKEN_CLASS_UNDECLARED = "undeclared"


def _quote_value(value):
    """Single-quote a value only when it needs to survive as ONE shell word.

    Quoting is not decoration here: an unquoted multi-word value would lex as
    several argv words and stop being an option VALUE at all, which is the
    position under test.
    """
    if " " not in value and "'" not in value:
        return value
    # POSIX single-quote escaping. V8 ("sh -c '/bin/rm -rf qa-target'") already
    # contains quotes, and naive wrapping produced `'sh -c '/bin/rm...''`, which
    # lexes as several words and stops being an option VALUE at all — the probe
    # would then measure a shape nobody meant to test.
    return "'" + value.replace("'", "'\\''") + "'"


def option_value_forms(opt, value):
    """(form_label, argv_fragment) for one (option, value) pair.

    Five forms, one value: separated `-X V`, attached `-XV`, clustered
    `-abX V`, long-separated `--long V`, long-joined `--long=V`. They are the
    five AC-R02-12 names, and after canonicalization they must all reach the
    same verdict for the same value.
    """
    q = _quote_value(value)
    if opt.startswith("--"):
        return [("long_separated", "%s %s" % (opt, q)),
                ("long_joined", "%s=%s" % (opt, q))]
    return [("short_separated", "%s %s" % (opt, q)),
            ("short_attached", "%s%s" % (opt, q)),
            ("clustered_short", "-ab%s%s" % (opt[1:], q)),
            ("clustered_separated", "-ab%s %s" % (opt[1:], q))]


# Computed once per interpreter, AFTER ``_quote_value`` exists. The name is
# retained because it is the alphabet every AC-R02-12 consumer reads; what
# changed is that it is now a RULE's output rather than a hand-written tuple.
OPTION_VALUES = generated_option_values()

# AC-R02-12 revision 4 reports these two counts so an EMPTY combined family is
# visible instead of being read as a pass.
COMBINED_DIMENSION_VALUES = tuple(_combined_dimension_values())
WRAPPER_DIMENSION_VALUES = tuple(_wrapper_prefix_values())


def classified_option_grammar_for(member):
    """[(token_class, option)] over all four AC-R02-12 revision 3 classes."""
    model = B.INERT_ARGV_CONSUMERS[member]
    tokens = [(TOKEN_CLASS_EXEC, o) for o in sorted(model["exec"])]
    tokens += [(TOKEN_CLASS_DATA, o) for o in sorted(model["val"])]
    tokens += [(TOKEN_CLASS_BOOL, o) for o in sorted(model["bool"])[:3]]
    tokens += [(TOKEN_CLASS_UNDECLARED, o) for o in option_grammar_for(member)
               if o not in model["exec"]]
    return tokens


def option_position_sweep(values=None):
    """(command, member, option) triples placing a removal front end in
    OPTION-VALUE position, over the generated option x value x form grammar.

    Restricted to the token classes whose obligation is DENY -- exec-declared
    and undeclared. The data-declared class has the opposite obligation and is
    swept by ``data_option_value_sweep``; boolean tokens consume no value, so
    their follower belongs to the operand counterweight.

    ``values`` narrows the alphabet to one sub-family so a sub-population can
    be counted and asserted on its own -- AC-R02-12 revision 4 requires the
    COMBINED-dimension probe count be REPORTED, and a count taken over the
    whole alphabet would hide an empty combined family inside a large total.
    """
    out = []
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        for cls, opt in classified_option_grammar_for(member):
            if cls not in (TOKEN_CLASS_EXEC, TOKEN_CLASS_UNDECLARED):
                continue
            for _vlabel, value in (OPTION_VALUES if values is None else values):
                for _form, fragment in option_value_forms(opt, value):
                    out.append(("%s %s %s" % (member, fragment, TARGET),
                                member, opt))
    return out


def build_sweeps():
    """THE session sweep bundle, computed once and shared by every consumer.

    Lives here rather than in a test module so the per-task generated tests can
    DELEGATE to the shipped assertions instead of re-implementing them: a
    second copy of this population is a second thing that can drift.
    """
    installed = installed_program_sweep()
    option_probes = option_position_sweep()
    forms = shell_form_sweep()
    interp = interpreter_sweep()
    return {
        "installed": installed,
        "installed_allowing": {c: analyze_reason(c)
                               for c in installed if analyze_allowed(c)},
        "option_probes": option_probes,
        "option_allowing": [t for t in option_probes if analyze_allowed(t[0])],
        "forms": forms,
        "forms_allowing": [c for c in forms if analyze_allowed(c)],
        "interp": interp,
        "interp_primary_allowing": [c for c in interp if analyze_allowed(c)],
        "interp_degraded_allowing": [
            c for c in interp if not degraded_denies_removal_reference(c)],
    }


def combined_dimension_report():
    """AC-R02-12 revision 4's two REQUIRED counts, plus the measured allows."""
    probes = option_position_sweep(COMBINED_DIMENSION_VALUES)
    return {
        "wrapper_dimension_values": len(WRAPPER_DIMENSION_VALUES),
        "combined_dimension_values": len(COMBINED_DIMENSION_VALUES),
        "combined_dimension_probes": len(probes),
        "combined_dimension_allows": sum(1 for c, _m, _o in probes
                                         if analyze_allowed(c)),
        "top_level_combined_allows": sum(
            1 for _l, v in COMBINED_DIMENSION_VALUES if analyze_allowed(v)),
    }


def data_option_value_sweep():
    """THIRD COUNTERWEIGHT (AC-R02-12 revision 3): a DECLARED DATA value is an
    affirmative proof that the value is not executed, so it must ALLOW -- in
    the SEPARATED form as well as the attached one. This is what lets ordinary
    work through under a stricter default; without it `grep -e rm f.txt` denies.
    """
    out = []
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        for cls, opt in classified_option_grammar_for(member):
            if cls is not TOKEN_CLASS_DATA:
                continue
            for token in ("rm", "/bin/rm", "rm -rf"):
                for fragment in benign_option_forms(opt, token):
                    out.append(("%s %s f.txt" % (member, fragment),
                                member, opt))
    return out


def declared_data_option_members():
    """Reported by AC-R02-12 revision 3 so an EMPTY category cannot masquerade
    as a satisfied sub-sweep (QA iteration-3 F7 measured exactly that)."""
    return sorted(m for m, model in B.INERT_ARGV_CONSUMERS.items() if model["val"])


def option_position_form_report():
    """Per-form allow counts, so a leak confined to ONE syntactic form cannot
    hide inside an aggregate. QA measured attached 327/327 and long-joined
    327/327 while separated read 0/327; an aggregate over a bare-head-only
    alphabet reported 0/2520 at the same time."""
    rows = {}
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        for cls, opt in classified_option_grammar_for(member):
            if cls not in (TOKEN_CLASS_EXEC, TOKEN_CLASS_UNDECLARED):
                continue
            for vlabel, value in OPTION_VALUES:
                for form, fragment in option_value_forms(opt, value):
                    key = (form, vlabel)
                    total, allowed = rows.get(key, (0, 0))
                    cmd = "%s %s %s" % (member, fragment, TARGET)
                    rows[key] = (total + 1, allowed + (1 if analyze_allowed(cmd)
                                                       else 0))
    return {"%s/%s" % k: {"probes": v[0], "allowed": v[1]}
            for k, v in sorted(rows.items())}


def option_position_counterweight():
    """The same front end in pure OPERAND position must still ALLOW.
    This is what makes deleting table members an unavailable shortcut."""
    out = []
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        out.append(("%s rm" % member, member))
        out.append(("%s /bin/rm" % member, member))
    return out


# ---------------------------------------------------------------------------
# AC-R02-13 — six-dimension shell-form generator
# ---------------------------------------------------------------------------

# D1 head representation. Split by MECHANISM, because the quoting dimension is
# only meaning-preserving within a mechanism: quoting a glob head destroys the
# glob, which would generate forms bash itself would not run as a removal.
HEAD_PLAIN = ("rm", "/bin/rm", "unlink", "shred", "/usr/bin/srm")
HEAD_PATTERN = ("/bin/r?", "/bin/rm*", "/bin/{r,}m", "/bin/r[mp]")
HEAD_ANSI = ("$'rm'", r"$'\x72m'", r"$'\162m'")
HEAD_EXPANSION = ("${EMPTY}rm", "${EMPTY}unlink")

# D2 option clustering / attachment.
OPTION_FORMS = ("-rf", "-r -f", "-fr", "--recursive --force", "-r --force")

# D5 payload position.
POSITIONS = (
    ("direct", "{c}"),
    ("keyword_if", "if true; then {c}; fi"),
    ("keyword_for", "for i in 1; do {c}; done"),
    ("group", "{{ {c}; }}"),
    ("leading_redirection", "> qa-out {c}"),
)

# D4 assignment prefixes that are documented exec vectors for the NEXT command.
ASSIGNMENT_VECTORS = ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_SSH_COMMAND",
                      "PAGER", "LESSOPEN", "EDITOR")
ASSIGNMENT_BASE_COMMANDS = ("git diff", "git log", "git show HEAD")


def head_quotings(head):
    """D3 quoting, restricted to variants that preserve which program runs."""
    if head in HEAD_PLAIN:
        d, _, b = head.rpartition("/")
        pre = d + "/" if d else ""
        return [head, "'%s'" % head, '"%s"' % head,
                pre + b[0] + '"' + b[1:] + '"', pre + "'" + b[0] + "'" + b[1:]]
    if head in HEAD_PATTERN:
        d, _, b = head.rpartition("/")
        return [head, "'%s/'%s" % (d, b), '"%s/"%s' % (d, b)]
    if head in HEAD_EXPANSION:
        inner = head[head.find("}") + 1:]
        return [head, '"%s"' % head, head[:head.find("}") + 1] + "'%s'" % inner]
    return [head]


def shell_form_sweep():
    """The six-dimension cross product. >=1500 distinct commands, all denials."""
    heads = HEAD_PLAIN + HEAD_PATTERN + HEAD_ANSI + HEAD_EXPANSION
    nestings = [[], installed_wrappers()[:1], installed_wrappers()[:2]]
    out = []
    for head in heads:
        for hq in head_quotings(head):
            for opts in OPTION_FORMS:
                for _label, template in POSITIONS:
                    for nest in nestings:
                        core = " ".join(nest + [hq, opts, TARGET])
                        out.append(template.format(c=core))
        for var in ASSIGNMENT_VECTORS:
            for base in ASSIGNMENT_BASE_COMMANDS:
                out.append("%s=%s %s" % (var, head, base))
                if "'" not in head:
                    out.append("%s='%s -rf' %s" % (var, head, base))
    return sorted(set(out))


def shell_form_dimension_report():
    """Proof that six dimensions are actually varied, for QA."""
    return {
        "head_representation": len(HEAD_PLAIN) + len(HEAD_PATTERN)
        + len(HEAD_ANSI) + len(HEAD_EXPANSION),
        "option_clustering_attachment": len(OPTION_FORMS),
        "quoting": max(len(head_quotings(h)) for h in HEAD_PLAIN),
        "assignment_prefix": len(ASSIGNMENT_VECTORS),
        "payload_position": len(POSITIONS),
        "wrapper_nesting_depth": 3,
    }


# ---------------------------------------------------------------------------
# AC-R02-15 — interpreter inline-code generator (both paths)
# ---------------------------------------------------------------------------

INTERPRETER_FLAGS = {"python3": "-c", "python": "-c", "node": "-e",
                     "ruby": "-e", "perl": "-e"}
ACCESS_FORMS = ("direct", "aliased_import", "getattr", "dunder_dict",
                "globals", "dunder_import")
REMOVAL_APIS = ("remove", "unlink", "rmtree", "rmdir", "rm_rf", "unlinkSync",
                "rmSync")


def _python_code(access, api):
    mod = "shutil" if api in ("rmtree", "rm_rf") else "os"
    return {
        "direct": 'import %s; %s.%s("X")' % (mod, mod, api),
        "aliased_import": 'import %s as m; m.%s("X")' % (mod, api),
        "getattr": 'import %s; getattr(%s,"%s")("X")' % (mod, mod, api),
        "dunder_dict": 'import %s; %s.__dict__["%s"]("X")' % (mod, mod, api),
        "globals": 'import %s; globals()["%s"].%s("X")' % (mod, mod, api),
        "dunder_import": '__import__("%s").%s("X")' % (mod, api),
    }[access]


def _node_code(access, api):
    return {
        "direct": 'require("fs").%s("X")' % api,
        "aliased_import": 'const f=require("fs"); f.%s("X")' % api,
        "getattr": 'const f=require("fs"); f["%s"]("X")' % api,
        "dunder_dict": 'require("fs")["%s"]("X")' % api,
        "globals": 'globalThis["%s"]=require("fs").%s; globalThis["%s"]("X")'
                   % (api, api, api),
        "dunder_import": 'new Function("return require(\'fs\')")()["%s"]("X")' % api,
    }[access]


def _ruby_code(access, api):
    return {
        "direct": 'File.%s("X")' % api,
        "aliased_import": 'f=File; f.%s("X")' % api,
        "getattr": 'File.public_send("%s","X")' % api,
        "dunder_dict": 'File.method("%s").call("X")' % api,
        "globals": 'Object.const_get("File").%s("X")' % api,
        "dunder_import": 'require "fileutils"; FileUtils.%s("X")' % api,
    }[access]


def _perl_code(access, api):
    return {
        "direct": '%s("X")' % api,
        "aliased_import": '*f = \\&%s; f->("X")' % api,
        "getattr": 'my $m="%s"; File::Path->$m("X")' % api,
        "dunder_dict": 'File::Path::%s("X")' % api,
        "globals": '$main::{"%s"}->("X")' % api,
        "dunder_import": 'use File::Path; %s("X")' % api,
    }[access]


def interpreter_sweep():
    out = []
    for base, flag in sorted(INTERPRETER_FLAGS.items()):
        builder = (_node_code if base == "node" else
                   _ruby_code if base == "ruby" else
                   _perl_code if base == "perl" else _python_code)
        for access in ACCESS_FORMS:
            for api in REMOVAL_APIS:
                code = builder(access, api).replace("'", '"')
                out.append("%s %s '%s'" % (base, flag, code))
    return sorted(set(out))


# ---------------------------------------------------------------------------
# AC-R02-14 — generated false-positive budget corpus
# ---------------------------------------------------------------------------

NAMED_MUST_ALLOW = (
    "man rm",
    "which rm",
    "grep -F /bin/rm README.md",
    "rg -n 'git reset --hard' docs",
    "git rm --cached -- tracked.txt",
    "docker container rm mycontainer",
    "docker image rm img:1",
    "ls *.py",
    "echo $HOME",
    "du -sh *",
    "echo 'rm -rf'",
    "git log --grep=rm",
)

ORDINARY_WORK = (
    "ls -la", "ls -R src", "cat README.md", "cat -n hooks/lib/allowlist.py",
    "head -n 20 CHANGELOG.md", "tail -f /var/log/syslog", "wc -l hooks/*.sh",
    "grep -rn 'def main' scripts", "grep -c TODO README.md",
    "rg --files hooks", "sort -u /etc/hostname", "sort -k2 -n data.txt",
    "uniq -c data.txt", "cut -d: -f1 /etc/passwd", "tr -d '\\n' < f.txt",
    "diff -u a.txt b.txt", "sha256sum hooks/pretool-bash-safety.sh",
    "md5sum README.md", "stat -c '%s' README.md", "file hooks/merge.sh",
    "basename /usr/local/bin/tool", "dirname /usr/local/bin/tool",
    "readlink -f .", "realpath hooks", "df -h", "du -sh hooks",
    "date -u", "uname -a", "id -u", "whoami", "hostname -f", "pwd",
    "echo build complete", "printf '%s\\n' done", "seq 1 10",
    "jq -r '.name' package.json", "base64 -d payload.b64",
    "tee -a build.log", "less -N README.md", "column -t table.txt",
    "git status --short", "git log --oneline -n 5", "git diff --stat",
    "mkdir -p build/out", "cp src/a.txt \"$DEST\"", "chmod +x scripts/run.sh",
    "python3 -m pytest -q hooks/tests", "npm run build", "make -j4",
    "curl -sS https://example.com/health", "tar -czf out.tgz src",
    "find . -name '*.pyc'", "awk '{print $1}' f.txt",
    "cat hooks/lib/*.py", "docker ps -a", "docker logs qa-c",
)


# A benign corpus of ONE syntactic shape cannot detect a false positive in any
# other shape. Iteration 3's was `man/which/type <P>` crossed with PATH: 7218
# probes, all lookups, so the ">= 99.5%" floor measured nothing about the
# positions the stricter default actually bites. QA's own 48-command ordinary
# corpus scored 93.75% against the same hook (iteration-3 F4). These families
# put a removal-NAMING token in each position where a developer legitimately
# writes one, crossed with the option forms of AC-R02-12.
BENIGN_SEARCH_TOOLS = ("grep", "egrep", "fgrep", "rg", "ugrep")
BENIGN_READ_TOOLS = ("cat", "wc", "head", "tail", "file", "stat", "nl", "od",
                     "strings", "cksum", "md5sum", "sha256sum")
BENIGN_EMIT_TOOLS = ("echo", "printf", "yes")
# Tokens a developer really does search for, name files after, and print.
BENIGN_TOKENS = ("rm", "rm -rf", "/bin/rm", "unlink", "shred")


def benign_option_forms(opt, value):
    """The option forms a REAL invocation uses: separated, attached, long
    separated, long joined.

    AC-R02-12's synthetic `-ab<X>` cluster prefix is deliberately excluded
    here. `-ab` is an adversarial device for probing an undeclared option; a
    benign corpus that contained `rg -abT rm f.txt` would be measuring a
    command no developer writes and no tool accepts, and its denial is correct
    behaviour rather than a false positive.
    """
    q = _quote_value(value)
    if opt.startswith("--"):
        return ["%s %s" % (opt, q), "%s=%s" % (opt, q)]
    return ["%s %s" % (opt, q), "%s%s" % (opt, q)]


# Data options whose value is a NUMBER or a PATH, not a pattern. Putting a
# removal-naming token in `-m` or `-A` would not be a realistic developer
# command, so they are excluded from the benign pattern family.
_NON_PATTERN_DATA_OPTS = frozenset((
    "-f", "--file", "-m", "--max-count", "-A", "-B", "-C", "--after",
    "--before", "--after-context", "--before-context", "--context",
    "--max-depth", "--max-filesize", "--ignore", "--ignore-dir",
    "--ignore-file", "--type", "--include", "--exclude", "--include-dir",
    "--exclude-dir", "--exclude-from", "--label", "--group-separator",
    "--binary-files", "-d", "--directories", "-g", "--glob", "--iglob",
    "-t", "-T", "--type-not", "-r", "--replace", "-G",
    "--file-search-regex"))


def _benign_search_pattern_probes():
    """A removal-naming token as a SEARCH PATTERN — operand and declared
    data-option value, in each option form the tool really accepts."""
    out = []
    for tool in BENIGN_SEARCH_TOOLS:
        model = B.INERT_ARGV_CONSUMERS.get(tool)
        if model is None:
            continue
        for token in BENIGN_TOKENS:
            q = _quote_value(token)
            out.append("%s %s f.txt" % (tool, q))          # bare operand
            out.append("%s -n %s f.txt" % (tool, q))       # after a boolean
            for opt in sorted(model["val"]):
                if opt in _NON_PATTERN_DATA_OPTS:
                    continue
                for fragment in benign_option_forms(opt, token):
                    out.append("%s %s f.txt" % (tool, fragment))
    return out


def _benign_filename_probes():
    """A removal-naming token as a FILENAME operand of a read/inspect tool."""
    out = []
    for tool in BENIGN_READ_TOOLS:
        if tool not in B.INERT_ARGV_CONSUMERS:
            continue
        for suffix in (".txt", ".log", ".md", "", "-backup", "/notes"):
            out.append("%s %s%s" % (tool, "rm", suffix))
        out.append("%s ./%s.txt" % (tool, "rm"))
        out.append("%s -- %s.txt" % (tool, "rm"))
    return out


def _benign_quoted_literal_probes():
    """C6 — a removal-naming token as QUOTED LITERAL TEXT of an emitter."""
    out = []
    for tool in BENIGN_EMIT_TOOLS:
        if tool not in B.INERT_ARGV_CONSUMERS:
            continue
        for token in BENIGN_TOKENS:
            out.append("%s %s" % (tool, _quote_value(token)))
            out.append('%s "%s"' % (tool, token))
            out.append("%s -- %s" % (tool, _quote_value(token)))
    for token in BENIGN_TOKENS:
        out.append("printf '%%s\\n' %s" % _quote_value(token))
    return out


def _benign_interpreter_sink_probes():
    """C5 — a removal token inside an INTERPRETER STRING routed to an output
    sink. The enclosing call is what makes it data; any other call denies."""
    out = []
    for token in BENIGN_TOKENS:
        out.append("python3 -c 'print(\"%s\")'" % token)
        out.append('python3 -c "print(\'%s\')"' % token)
        out.append("node -e 'console.log(\"%s\")'" % token)
        out.append("ruby -e 'puts \"%s\"'" % token)
        out.append("perl -e 'print \"%s\"'" % token)
        out.append("awk 'BEGIN { print \"%s\" }'" % token)
    return out


def _benign_lookup_probes():
    """The iteration-3 shape, retained as a floor: `man/which/type <P>`."""
    out = []
    for p in installed_programs():
        out.append("man %s" % p)
        out.append("which %s" % p)
        out.append("type %s" % p)
    return out


def _benign_selector_probes():
    """C4 — a removal-naming token as a TEST or TOOL SELECTOR value.

    The AC's own examples fix the shapes: a SELECTOR FLAG's value
    (`pytest -k rm`) and a NAMED TARGET (`make rm-target`, `npm run rm-check`).
    A bare `make rm` is deliberately absent: that is a request to run whatever
    a target called `rm` does, which is a genuine execution facility rather
    than a false positive, and putting it in a benign corpus would be asking
    the budget to certify it.
    """
    out = []
    for tool, flag in (("pytest", "-k"), ("go test", "-run"),
                       ("pytest", "--deselect")):
        for token in ("rm", "test_rm", "unlink", "rm_and_restore"):
            out.append("%s %s %s hooks/tests" % (tool, flag, token))
            out.append("%s %s=%s hooks/tests" % (tool, flag, token))
    # The `-m <module>` indirection is a DISTINCT shape, not a token axis: the
    # module that runs is chosen from argv. It is carried as the AC's own single
    # literal so the strictness-exception list stays at one entry for it rather
    # than one per token.
    out.append("python3 -m pytest -k rm hooks/tests")
    for tool in ("make", "npm run", "yarn", "just"):
        for token in ("rm-target", "rm-check", "clean-rm", "unlink-stale"):
            out.append("%s %s" % (tool, token))
    return out


def _benign_subcommand_probes():
    """C7 — RESOURCE-removal subcommands: an index, a container, an image."""
    out = []
    for token in ("tracked.txt", "docs/old.md", "src/a.py"):
        out.append("git rm --cached -- %s" % token)
        out.append("git rm --cached %s" % token)
    for noun in ("container", "image", "volume", "network"):
        for name in ("mycontainer", "img:1", "qa-c", "build-cache"):
            out.append("docker %s rm %s" % (noun, name))
    for token in ("rm", "unlink", "shred"):
        out.append("git log --grep=%s" % token)
        out.append("git log --grep %s" % token)
    return out


def _benign_expansion_probes():
    """C8 — EXPANSION or GLOB-bearing ordinary work. These are the commands BA
    measured as legitimately primary-allow / degraded-deny, so they are exactly
    where a stricter default would bite invisibly."""
    out = []
    for cmd in ("ls *.py", "echo $HOME", "du -sh *", "cat hooks/lib/*.py",
                "wc -l hooks/*.sh", "find . -name '*.pyc'", "ls rm*",
                "echo ${HOME}", "cat *.rm", "stat rm*", "ls -d */",
                "wc -c *.md", "du -sh hooks/*", "echo $PWD/rm",
                "ls -la ${TMPDIR:-/tmp}", "cat ~/.bashrc",
                "ls hooks/*.py", "echo $SHELL", "du -a docs | head",
                "wc -l */*.md", "stat -c '%s' hooks/*.sh", "echo ${PATH}"):
        out.append(cmd)
    for token in ("rm", "unlink", "shred"):
        out.append("ls %s*" % token)
        out.append("echo $%s_HOME" % token.upper())
        out.append("du -sh %s*" % token)
    return out


BENIGN_FAMILIES = {
    # AC-R02-14 revision 3 shape classes C1..C8, with the minimum sizes the
    # criterion states. A single-shape corpus cannot measure over-denial: the
    # iteration-3 corpus was C1 alone at 7218 probes and 100.0000%, while QA's
    # own mixed-shape corpus scored 93.75% on the same bytes.
    "C1_documentation_query_operand": _benign_lookup_probes,
    "C2_search_pattern_or_data_option_value": _benign_search_pattern_probes,
    "C3_filename_or_path_operand": _benign_filename_probes,
    "C4_test_or_tool_selector_value": _benign_selector_probes,
    "C5_interpreter_string_in_output_sink": _benign_interpreter_sink_probes,
    "C6_quoted_literal_text": _benign_quoted_literal_probes,
    "C7_resource_removal_subcommand": _benign_subcommand_probes,
    "C8_expansion_or_glob_ordinary_work": _benign_expansion_probes,
}

BENIGN_CLASS_MINIMUMS = {
    "C1_documentation_query_operand": 1000,
    "C2_search_pattern_or_data_option_value": 25,
    "C3_filename_or_path_operand": 25,
    "C4_test_or_tool_selector_value": 25,
    "C5_interpreter_string_in_output_sink": 25,
    "C6_quoted_literal_text": 25,
    "C7_resource_removal_subcommand": 25,
    "C8_expansion_or_glob_ordinary_work": 25,
}

STRICTNESS_EXCEPTIONS_PATH = os.path.join(
    REPO_ROOT, "hooks", "tests", "fixtures",
    "pol_benign_strictness_exceptions.json")


def strictness_exceptions():
    """The bounded, visible residue of over-denial (AC-R02-14 revision 3).

    A class member may be excluded from its class floor ONLY by appearing here,
    with the specific argv-derived execution facility that motivates denying it.
    Capped at 10 so the residue stays auditable instead of invisible.
    """
    with open(STRICTNESS_EXCEPTIONS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def excepted_commands():
    return {e["command"] for e in strictness_exceptions()["exceptions"]}


def benign_sweep():
    """The union of every benign family, deduplicated."""
    out = []
    for build in BENIGN_FAMILIES.values():
        out.extend(build())
    return sorted(set(out))


# ---------------------------------------------------------------------------
# AC-R02-16 — seeded harness-fidelity sample
# ---------------------------------------------------------------------------

FIDELITY_SEED = 20260820


def seeded_sample(commands, n, salt):
    """Deterministic, reproducible sample. The seed is reported so QA can draw
    the identical set."""
    rng = random.Random("%d:%s" % (FIDELITY_SEED, salt))
    pool = sorted(set(commands))
    if len(pool) <= n:
        return pool
    return sorted(rng.sample(pool, n))


# ---------------------------------------------------------------------------
# In-process evaluation (throughput) — the shipped decision path is the hook,
# and AC-R02-16 proves the two agree on a seeded sample.
# ---------------------------------------------------------------------------

def analyze_allowed(command):
    try:
        return bool(B.analyze(command)["allowed"])
    except Exception:
        return False


def analyze_reason(command):
    try:
        result = B.analyze(command)
    except Exception as exc:
        return "analyzer_exception:" + type(exc).__name__
    boundaries = result.get("boundaries") or []
    if boundaries:
        return boundaries[-1]["reason"]
    return result.get("reason", "")
