"""Rule-generated acceptance tests for the LANE-POL removal policy.

AC-R02-10 .. AC-R02-16 (revision 2). Every deny-side population here is
computed at run time from a generator or a runtime-derived set, never from a
checked-in list of strings — because a fixed corpus cannot observe a leak that
MUTATES between iterations. Iteration 1 authorized on ABSENCE (unmodelled head
-> PROVEN_INERT); iteration 2 authorized on MEMBERSHIP (head in a table ->
PROVEN_INERT without reading the argv); the pinned 436-row corpus reported
"passes" both times.

ZERO EXECUTION (AC-R02-06): every generated string is data. It is analyzed
in-process or delivered to the hook as JSON on stdin. Nothing here executes,
expands or evals a generated command.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess

import pytest

import pol_replay_harness as H
import pol_sweep_generators as G

import bash_execution_boundary as B

LEDGER_PATH = os.path.join(G.REPO_ROOT, "hooks", "tests", "fixtures",
                           "pol_primary_laxity_ledger.json")
ALLOW_SET_PATH = os.path.join(G.REPO_ROOT, "hooks", "tests", "fixtures",
                              "pol_installed_program_allow_set.json")

# The allow-set is a QA DIFFING AID, never a test input: nothing reads it back.
# Writing it unconditionally therefore bought nothing and cost a ~34 KB working
# tree modification on every single run, which is noise a reviewer has to
# re-classify each time. The artifact is still produced -- so a payload that
# cannot be serialized still fails -- but its default destination is a
# temporary file, and the in-repo copy is refreshed only when this variable is
# set to a non-empty value.
ALLOW_SET_REFRESH_ENV = "POL_REFRESH_ALLOW_SET"

# The blanket reason code AC-R02-10/11 declare inadmissible: it authorized an
# entire argv without inspecting a single word of it.
INADMISSIBLE_REASON_CODES = ("inert_argv_consumer",)

# AC-R02-10's CLOSED admissible-proof-kind set, now NINE kinds. (6)/(7) were
# admitted by revision 3 and (8)/(9) by revision 4, each because it is FORCED
# by the unrelaxable AC-R02-01 over named pinned expected_exit=0 fixture rows —
# so the conflict is resolved on the criteria side, never by denying a pinned
# row, never by mislabelling its position, and never as a standing dev
# deviation. Each addition is bounded to exactly one positional shape.
ADMISSIBLE_PROOF_KINDS = (
    "proven-safe cached-git removal",
    "proven-safe container/image resource removal",
    "operand of a documentation/query consumer",
    "search-pattern operand",
    "literal output text",
    "parse-only shell payload - active but non-executing",
    "quoted data operand of a named interpreter script FILE",
    "stdin-delivered redirection payload of a consumer that does not execute its stdin",
    "pre-command variable binding the following command does not execute",
)

# Revision 4 binds each added kind to exactly ONE shape, so widening the proof
# set cannot create absorption room anywhere else.
PROOF_KIND_SHAPE_BOUND = {
    "stdin-delivered redirection payload of a consumer that does not execute "
    "its stdin": B.SHAPE_HEREDOC_BODY,
    "pre-command variable binding the following command does not execute":
        B.SHAPE_ASSIGNMENT_PREFIX,
}


# ---------------------------------------------------------------------------
# Session-scoped sweeps (in-process, ~1 s for ~14000 probes)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sweeps():
    # Body moved to G.build_sweeps() so the per-task generated tests can share
    # the SAME population rather than growing a second copy of it.
    return G.build_sweeps()


# ---------------------------------------------------------------------------
# AC-R02-11 — installed-program argv sweep (population from PATH at test time)
# ---------------------------------------------------------------------------

def test_ac_r02_11_program_set_is_derived_at_runtime():
    programs = G.installed_programs()
    assert len(programs) > 100, "PATH enumeration produced an implausible set"
    source = open(os.path.join(G.REPO_ROOT, "hooks", "tests",
                               "pol_sweep_generators.py"), encoding="utf-8").read()
    # A snapshot of the program set (or of its size) would reintroduce exactly
    # the corpus binding this criterion exists to remove.
    assert "os.environ" in source and "PATH" in source
    assert str(len(programs)) not in source


def test_ac_r02_11_every_allowing_program_is_declared(sweeps):
    table = B.declared_authorizing_table()
    undeclared = []
    unjustified = []
    argv_uninspected = []
    for command, reason in sorted(sweeps["installed_allowing"].items()):
        program = command.split()[0]
        entry = table.get(program)
        if entry is None:
            undeclared.append((program, reason))
            continue
        if not entry["justification"].strip():
            unjustified.append(program)
        if any(reason.startswith(bad) for bad in INADMISSIBLE_REASON_CODES):
            argv_uninspected.append((program, reason))
    assert undeclared == [], "allowing programs absent from the declared table"
    assert unjustified == [], "declared entries without a written justification"
    assert argv_uninspected == [], "allows resting on an argv-uninspecting code"


# ---------------------------------------------------------------------------
# AC-R02-11 — the DECLARED DATA is the judgement-bearing surface, so it is
# cross-checked against the binaries actually installed on this host.
# ---------------------------------------------------------------------------

def test_ac_r02_11_declared_models_match_the_on_path_binary():
    """A member's written proof must be about the program that would RUN.

    `print` was declared with the ksh/zsh builtin's option model and the
    text-emission proof "no argv-derived program is executed", while
    /usr/bin/print on this host is run-mailcap — "execute programs via entries
    in the mailcap file" (QA iteration-3 F3). Reading the declaration could not
    reveal that; only cross-checking it against the installed binary could.
    """
    verbs = re.compile(r"\b(execut\w+|invok\w+|spawn\w+|launch\w+)\b", re.I)
    offenders = []
    checked = 0
    for name, model in sorted(B.INERT_ARGV_CONSUMERS.items()):
        path = shutil.which(name)
        if path is None:
            continue                      # shell builtin on this host
        checked += 1
        try:
            summary = subprocess.run(["whatis", name], capture_output=True,
                                     text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            summary = ""
        if verbs.search(summary or "") and not model["exec"]:
            offenders.append((name, "documented as executing programs: "
                              + summary.strip().splitlines()[0][:90]))
    if checked < 20:
        pytest.skip("too few table members installed to audit on this host")
    assert offenders == [], (
        "declared justification contradicts the on-PATH binary: %s" % offenders)


def test_ac_r02_11_script_members_do_not_eval_their_own_argv():
    """A member implemented as a shell script must not build and `eval` a
    command string from its argv.

    `zgrep` is a /bin/sh script whose argv reaches `eval "cat --$optarg"` and
    `eval "$grep$args"`. The shell-quoting applied first is why no exploit
    follows, but the declared proof said the program exposes no argv-derived
    exec facility, and a mitigated facility is still a facility.
    """
    offenders = []
    for name, model in sorted(B.INERT_ARGV_CONSUMERS.items()):
        path = shutil.which(name)
        if path is None or model["exec"]:
            continue
        try:
            with open(path, "rb") as handle:
                if handle.read(2) != b"#!":
                    continue
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for match in re.finditer(r"^[^#\n]*?\beval\s+([\"'])(.*?)\1",
                                 text, re.M | re.S):
            body = match.group(2)
            if "$" not in body:
                continue            # a fixed string cannot carry argv
            # The Perl polyglot re-exec header
            #     eval 'exec /usr/bin/perl -S $0 ${1+"$@"}'
            #         if 0;
            # names a FIXED interpreter and the `if 0` guard means perl never
            # runs it; the expansions are positional parameters handed TO that
            # interpreter, not a command string assembled from argv. This is a
            # named idiom, not a general exemption.
            if re.match(r"\s*;?\s*\n?\s*if\s+0\s*;",
                        text[match.end():match.end() + 48]):
                continue
            offenders.append((name, path, body[:60]))
            break
    assert offenders == [], (
        "script members that eval an argv-derived string: %s" % offenders)


def test_argv_eval_detector_is_not_vacuous():
    """The audit above passes trivially if its detector never fires. `zgrep` is
    the control: on PATH, a shell script, and REMOVED from the table this
    iteration for exactly this reason."""
    control = shutil.which("zgrep")
    if control is None:
        pytest.skip("no zgrep on this host to use as a positive control")
    assert "zgrep" not in B.INERT_ARGV_CONSUMERS, (
        "zgrep is declared inert again; its argv reaches eval")
    text = open(control, encoding="utf-8", errors="replace").read()
    fired = False
    for match in re.finditer(r"^[^#\n]*?\beval\s+([\"'])(.*?)\1",
                             text, re.M | re.S):
        if "$" not in match.group(2):
            continue
        if re.match(r"\s*;?\s*\n?\s*if\s+0\s*;",
                    text[match.end():match.end() + 48]):
            continue
        fired = True
        break
    assert fired, "detector failed to fire on a known argv-eval script"
    assert "print" not in B.INERT_ARGV_CONSUMERS, (
        "print is declared inert again; /usr/bin/print is run-mailcap")


def test_ac_r02_11_counterweight_lookups_still_allow():
    denied = [c for c in G.installed_program_counterweight()
              if not G.analyze_allowed(c)]
    assert denied == [], "man <P> / which <P> must allow for every program"


def test_ac_r02_11_emits_allow_set_artifact(sweeps, tmp_path):
    """The allowing set is written out so QA can diff it across iterations.

    Destination is a temporary file unless POL_REFRESH_ALLOW_SET is set, so an
    ordinary run leaves the working tree exactly as it found it.
    """
    table = B.declared_authorizing_table()
    payload = {
        "schema": "pol-installed-program-allow-set.v1",
        "criterion": "AC-R02-11",
        "probe_shape": "<P> /bin/rm -rf qa-target (analyzed, never executed)",
        "program_set_size": len(G.installed_programs()),
        "allowing_count": len(sweeps["installed_allowing"]),
        "allowing": {
            command.split()[0]: {
                "boundary_reason_code": reason,
                "justification": table[command.split()[0]]["justification"],
                "proof_kind": table[command.split()[0]]["proof_kind"],
                "argv_derived_execution_facility":
                    table[command.split()[0]]["argv_derived_execution_facility"],
            }
            for command, reason in sorted(sweeps["installed_allowing"].items())
        },
    }
    destination = (ALLOW_SET_PATH if os.environ.get(ALLOW_SET_REFRESH_ENV)
                   else str(tmp_path / os.path.basename(ALLOW_SET_PATH)))
    with open(destination, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
        fh.write("\n")
    assert payload["allowing_count"] == len(payload["allowing"])


# ---------------------------------------------------------------------------
# AC-R02-12 — positional discrimination over the authorizing table
# ---------------------------------------------------------------------------

def test_ac_r02_12_option_value_position_always_denies(sweeps):
    leaking = sorted({(m, o) for _c, m, o in sweeps["option_allowing"]})
    assert leaking == [], (
        "removal front end allowed in option-value position for %d (member, "
        "option) pairs; sample: %s" % (len(leaking), leaking[:10]))


def test_ac_r02_12_covers_every_table_member(sweeps):
    covered = {m for _c, m, _o in sweeps["option_probes"]}
    assert covered == set(B.INERT_ARGV_CONSUMERS)


def test_ac_r02_12_form_report_has_no_leaking_form(sweeps):
    """Per-form, per-value-class counts. An aggregate hid the iteration-3 leak:
    attached 327/327 and long-joined 327/327 allowed while the total read 0,
    because the value alphabet contained only bare removal heads."""
    leaking = {k: v for k, v in G.option_position_form_report().items()
               if v["allowed"]}
    assert leaking == {}, leaking


def test_canonicalization_makes_every_option_form_agree():
    """THE property the canonicalization exists to buy: for one value in one
    position, all five syntactic forms reach the same verdict.

    This is what three iterations lacked. Iteration 1 disagreed on presence,
    iteration 2 on membership, iteration 3 on attachment — each time two code
    paths answered one question and the laxer answer won.
    """
    divergent = []
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        for opt in G.option_grammar_for(member):
            for vlabel, value in G.OPTION_VALUES:
                verdicts = {}
                for form, fragment in G.option_value_forms(opt, value):
                    command = "%s %s %s" % (member, fragment, G.TARGET)
                    verdicts[form] = G.analyze_allowed(command)
                if len(set(verdicts.values())) > 1:
                    divergent.append((member, opt, vlabel, verdicts))
    assert divergent == [], (
        "%d (member, option, value) triples whose verdict depends on the "
        "SYNTACTIC FORM the value arrived in; sample: %s"
        % (len(divergent), divergent[:5]))


def _recognition_callables():
    """The banned set, DERIVED FROM THE MODULE rather than listed.

    QA iteration-4 F4 mutation-tested the old guard and measured it 1/7
    effective: it named four functions, so re-introducing recognition into the
    parse phase through any of the other seven names left it green. A list of
    names can only ban the names its author already thought of, which is the
    same corpus-binding failure the deny-side criteria exist to prevent.
    """
    pat = re.compile(r"removal|provably_inert")
    out = set()
    for name, value in vars(B).items():
        if callable(value) and pat.search(name):
            out.add(name)
    for name, value in vars(B.Analyzer).items():
        if pat.search(name) and (isinstance(value, staticmethod)
                                 or callable(value)):
            out.add(name)
    return out


def _function_defs(tree):
    defs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name, node)
    return defs


def _reaches(defs, start, banned):
    """Names in ``banned`` reachable from ``start`` through module-local calls.

    Transitive, so interposing a helper does not launder the call.
    """
    hits, seen, stack = [], {start}, [defs[start]]
    while stack:
        fn = stack.pop()
        for node in ast.walk(fn):
            name = (node.attr if isinstance(node, ast.Attribute)
                    else node.id if isinstance(node, ast.Name) else None)
            if name is None or name == fn.name:
                continue
            if name in banned:
                hits.append((fn.name, name))
            if name in defs and name not in seen:
                seen.add(name)
                stack.append(defs[name])
    return hits


def test_removal_recognition_has_a_single_entry_point():
    """PHASE SEPARATION, checked by call graph instead of by substring.

    ``_ic_canonicalize`` is phase 1: it reduces argv to canonical slots and
    decides nothing. Phase 2 asks the removal question ONCE, of an already
    canonical value. The guard walks the AST call graph out of phase 1 and
    asserts it reaches no removal-recognition callable — transitively, and over
    a banned set read off the module, so a name that does not exist yet is
    covered the day it is added.
    """
    banned = _recognition_callables()
    assert len(banned) >= 8, sorted(banned)
    tree = ast.parse(open(B.__file__, encoding="utf-8").read())
    defs = _function_defs(tree)
    hits = _reaches(defs, "_ic_canonicalize", banned)
    assert hits == [], (
        "the canonicalization phase reaches removal recognition: %s" % hits)


def test_phase_separation_guard_is_not_vacuous():
    """LIVE POSITIVE CONTROL for the guard above.

    A structural guard that cannot fail is worth nothing, and asserting that
    in a comment is not evidence. Two checks, both measured on the shipped
    source: phase 2 really does reach recognition (so the machinery detects a
    real call), and injecting each banned name into phase 1's body is really
    detected (so nothing about phase 1 makes it immune).
    """
    banned = _recognition_callables()
    source = open(B.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    defs = _function_defs(tree)
    assert _reaches(defs, "_inert_consumer", banned), (
        "phase 2 reaches no recognition callable: the guard's own detector is "
        "broken, not the code under it")

    header, body = source.split("    def _ic_canonicalize", 1)
    signature, rest = body.split("\n", 1)
    for name in sorted(banned):
        mutant = "%s    def _ic_canonicalize%s\n        %s(args)\n%s" % (
            header, signature, name, rest)
        mdefs = _function_defs(ast.parse(mutant))
        assert _reaches(mdefs, "_ic_canonicalize", banned), (
            "injecting %s into the canonicalization phase is NOT detected; "
            "the guard would stay green while phase separation is broken"
            % name)


def test_ac_r02_12_declared_data_values_allow(sweeps):
    """THIRD COUNTERWEIGHT (revision 3): a DECLARED DATA value is an affirmative
    proof that the value is not executed, so it must ALLOW — in the SEPARATED
    form as well as the attached one. Without it `grep -e rm f.txt` denies, and
    a stricter default starts breaking ordinary work."""
    members = G.declared_data_option_members()
    assert members, (
        "declared_data_option_members = 0: the data-value category has no "
        "members, so this sub-sweep would run empty (QA iteration-3 F7)")
    probes = G.data_option_value_sweep()
    denied = [t for t in probes if not G.analyze_allowed(t[0])]
    assert denied == [], denied[:8]
    assert G.analyze_allowed("grep -e rm f.txt")


def test_ac_r02_12_probe_count_meets_the_stated_minimum(sweeps):
    assert len(sweeps["option_probes"]) >= 4360, len(sweeps["option_probes"])


def test_ac_r02_12_value_alphabet_covers_the_stated_v1_v8():
    """The alphabet revision 3 states explicitly, so the criterion has exactly
    one reading instead of swinging 0% to 61% on an unstated one."""
    values = {v for _label, v in G.OPTION_VALUES}
    for required in ("/bin/rm",
                     "/bin/rm -rf qa-target",
                     "/bin/rm -r -f qa-target",
                     "/bin/rm --recursive --force qa-target",
                     "x; /bin/rm -rf qa-target",
                     "true && /bin/rm -rf qa-target",
                     "LC_ALL=C /bin/rm -rf qa-target",
                     "sh -c '/bin/rm -rf qa-target'"):
        assert required in values, required


def test_ac_r02_12_value_alphabet_is_closed_under_composition():
    """AC-R02-12 revision 4: single-dimension closure is not closure.

    The six dimensions were applied ONE AT A TIME, so the alphabet's 52 entries
    fell into disjoint families — 16 head/flag, 22 wrapper, 3 nesting, 3
    tokenization, 8 command-position — and never composed. A wrapper prefix
    INSIDE a nested shell, and a wrapper form whose separators are rewritten,
    are the natural next gap and the exact class this lane was rejected on
    twice. Required pairs: wrapper x nesting (depth 1 AND 2), wrapper x
    tokenization (${IFS}-joined AND unspaced-separator).
    """
    labels = {label for label, _v in G.COMBINED_DIMENSION_VALUES}
    values = {v for _l, v in G.OPTION_VALUES}
    wrappers = len(G.WRAPPER_DIMENSION_VALUES)
    for label, value in G.COMBINED_DIMENSION_VALUES:
        assert value in values, "combined value missing from the alphabet: %s" % label
    for name in (l[len("wrapper_"):] for l, _v in G.WRAPPER_DIMENSION_VALUES):
        for suffix in ("nested_depth_1", "nested_depth_2",
                       "ifs_joined", "separator_unspaced"):
            assert "wrapper_%s__%s" % (name, suffix) in labels, (name, suffix)
    # >= 2 x |wrapper dimension|, and > 0. A host with no installed exec
    # wrapper reports 0 rather than silently sweeping nothing.
    assert len(G.COMBINED_DIMENSION_VALUES) >= 2 * wrappers
    assert wrappers > 0 and len(G.COMBINED_DIMENSION_VALUES) > 0, (
        "no installed exec wrapper on this host; combined family is empty")


def test_ac_r02_12_combined_dimension_values_never_allow():
    """The deny obligation applies to the COMBINED values on the same terms.

    Both counts are REPORTED so an empty combined family is visible instead of
    being read as a pass.
    """
    report = G.combined_dimension_report()
    assert report["combined_dimension_values"] > 0, report
    assert report["combined_dimension_probes"] > 0, report
    assert report["top_level_combined_allows"] == 0, report
    assert report["combined_dimension_allows"] == 0, report


def test_ac_r02_12_operand_position_counterweight():
    """Deleting table members cannot satisfy the criterion: this half fails."""
    denied = [(c, m) for c, m in G.option_position_counterweight()
              if not G.analyze_allowed(c)]
    assert denied == [], "operand-position false positives: %s" % denied[:10]


def test_ac_r02_12_named_must_allow_operands():
    for command in ("man rm", "which rm", "grep -F /bin/rm README.md"):
        assert G.analyze_allowed(command), command


# ---------------------------------------------------------------------------
# AC-R02-13 — six-dimension shell-form generator
# ---------------------------------------------------------------------------

def test_ac_r02_13_generator_has_six_varied_dimensions():
    dims = G.shell_form_dimension_report()
    assert len(dims) >= 6
    assert all(v >= 2 for v in dims.values()), dims


def test_ac_r02_13_generates_at_least_1500_commands(sweeps):
    assert len(sweeps["forms"]) >= 1500, len(sweeps["forms"])


def test_ac_r02_13_all_generated_shell_forms_deny(sweeps):
    allowed = sweeps["forms_allowing"]
    assert allowed == [], "%d generated forms allowed; sample: %s" % (
        len(allowed), allowed[:10])


def test_ac_r02_13_disjoint_from_the_pinned_corpus(sweeps):
    """The corpus and the generator must not be measuring the same thing."""
    fixture = {r["command"] for r in H.load_fixture()["rows"]}
    assert not (set(sweeps["forms"]) & fixture)


# ---------------------------------------------------------------------------
# AC-R02-15 — interpreter inline-code generator, BOTH paths
# ---------------------------------------------------------------------------

def test_ac_r02_15_primary_path_denies_every_form(sweeps):
    assert sweeps["interp_primary_allowing"] == [], \
        sweeps["interp_primary_allowing"][:10]


def test_ac_r02_15_degraded_path_denies_every_form(sweeps):
    assert sweeps["interp_degraded_allowing"] == [], \
        sweeps["interp_degraded_allowing"][:10]


def test_ac_r02_15_known_f5_leak_denies_on_both_paths():
    command = 'python3 -c \'import os; getattr(os,"remove")("/tmp/qa-t")\''
    assert not G.analyze_allowed(command)
    assert G.degraded_denies_removal_reference(command)


# ---------------------------------------------------------------------------
# AC-R02-14 — false-positive budget (the counterweight to every deny criterion)
# ---------------------------------------------------------------------------

def test_ac_r02_14_named_must_allow_set_is_100_percent():
    denied = [c for c in G.NAMED_MUST_ALLOW if not G.analyze_allowed(c)]
    assert denied == [], denied


def test_ac_r02_14_generated_benign_allow_rate():
    corpus = G.benign_sweep()
    denied = [c for c in corpus if not G.analyze_allowed(c)]
    rate = 100.0 * (len(corpus) - len(denied)) / len(corpus)
    assert rate >= 99.5, "allow-rate %.3f%%, denials: %s" % (rate, denied[:10])


def test_ac_r02_14_every_shape_class_meets_its_floor():
    """C1..C8, each with its own zero-unexcepted-denial floor.

    A global rate over a single-shape corpus is not a false-positive budget:
    iteration 3 measured 7218 probes at 100.0000% while every probe was the C1
    shape, and QA's own mixed-shape corpus scored 93.75% on the same bytes.
    """
    assert len(G.BENIGN_FAMILIES) >= 8, sorted(G.BENIGN_FAMILIES)
    excepted = G.excepted_commands()
    for family, build in sorted(G.BENIGN_FAMILIES.items()):
        corpus = sorted(set(build()))
        assert len(corpus) >= G.BENIGN_CLASS_MINIMUMS[family], (family, len(corpus))
        unexcepted = [c for c in corpus
                      if not G.analyze_allowed(c) and c not in excepted]
        assert unexcepted == [], (family, unexcepted[:5])


def test_ac_r02_14_strictness_exceptions_are_bounded_and_justified():
    """The residue of over-denial is visible and capped, not invisible."""
    data = G.strictness_exceptions()
    assert data["max_entries"] <= 10
    assert len(data["exceptions"]) <= data["max_entries"]
    for entry in data["exceptions"]:
        assert entry["command"].strip()
        assert entry["shape_class"] in G.BENIGN_FAMILIES, entry
        assert entry["argv_derived_execution_facility"].strip()
        # An exception must describe a REAL denial; a stale entry would
        # quietly widen the floor it is excluded from.
        assert not G.analyze_allowed(entry["command"]), entry["command"]
    assert not (G.excepted_commands() & set(G.NAMED_MUST_ALLOW))


def test_declared_data_value_category_is_not_dead():
    """`val` had zero members in iteration 3 and no behavioural effect, so the
    boundary's own description named a distinction that did not exist (QA
    iteration-3 F7). It is now the position that lets `grep -e rm f.txt`
    through, and nothing else about that command's shape does."""
    populated = {m for m, model in B.INERT_ARGV_CONSUMERS.items() if model["val"]}
    assert populated, "declared-data-value category is still empty"
    table = B.declared_authorizing_table()
    for member in sorted(populated):
        entry = table[member]
        assert entry["option_model"]["declared_data_value_justification"].strip()
        model = B.INERT_ARGV_CONSUMERS[member]
        overlap = model["val"] & (model["exec"] | model["bool"])
        assert not overlap, (member, sorted(overlap))
    assert G.analyze_allowed("grep -e rm f.txt")
    assert B.analyze("grep -e rm f.txt")["removal_positional_shape"] == \
        B.SHAPE_DATA_OPTION_VALUE
    # A declared DATA option must not become a hole for a declared EXEC one.
    assert not G.analyze_allowed("rg --pre /bin/rm needle .")


def test_declared_data_values_never_shadow_the_ac_r02_12_probe_set():
    """A member declaring one of the generic probe tokens as a data value would
    silently remove that token from the AC-R02-12 sweep. Asserted, not assumed.
    """
    collisions = []
    for member, model in sorted(B.INERT_ARGV_CONSUMERS.items()):
        for token in G.GENERIC_OPTION_PROBES:
            resolved = (B._resolve_ic_long(token, model)
                        if token.startswith("--") else token)
            if resolved in model["val"]:
                collisions.append((member, token))
    assert collisions == [], collisions


def test_ac_r02_14_fixture_safe_rows_and_ordinary_work_allow():
    safe = [r["command"] for r in H.load_fixture()["rows"]
            if r["expected_hook_exit_code"] == 0]
    denied = [c for c in safe + list(G.ORDINARY_WORK)
              if not G.analyze_allowed(c)]
    assert denied == [], denied[:10]


# ---------------------------------------------------------------------------
# AC-R02-10 — differential fail-closed invariant, restricted and ledgered
# ---------------------------------------------------------------------------

def _restricted_domain(sweeps):
    universe = [r["command"] for r in H.load_fixture()["rows"]]
    universe += sweeps["installed"]
    universe += G.installed_program_counterweight()
    universe += [c for c, _m, _o in sweeps["option_probes"]]
    universe += [c for c, _m in G.option_position_counterweight()]
    universe += sweeps["forms"]
    universe += sweeps["interp"]
    universe += list(ITERATION2_COUNTER_EXAMPLES)
    universe += list(REP_PROBES.values())
    # AC-R02-12 revision 3's declared-data-option counterweight is part of that
    # criterion's generator output, so it is in U by the domain's own terms —
    # and it is the only place the declared_data_option_value shape appears.
    universe += [c for c, _m, _o in G.data_option_value_sweep()]
    return sorted({c for c in set(universe)
                   if G.degraded_denies_removal_reference(c)})


def _non_absorption_control(sweeps):
    """AC-R02-10 revision 3's mandatory control family, regenerated here.

    Take members whose proof kinds are (3) documentation/query operand, (4)
    search-pattern operand and (5) literal output text — the three entries that
    absorbed QA's 981 elements — and move the removal reference OUT of operand
    position into the AC-R02-12 option-value alphabet. Every member must come
    back NOT-IN-L or UNLEDGERED. A member reported COVERED is the absorption
    this criterion exists to detect.
    """
    kinds = ("operand_of_documentation_or_query_consumer",
             "search_pattern_operand", "literal_output_text")
    members = [m for m, model in sorted(B.INERT_ARGV_CONSUMERS.items())
               if model["kind"] in kinds]
    # SECOND DIMENSION, added after QA iteration-4 F2. The iteration-4 control
    # built every member as `'%s %s %s' % (member, fragment, TARGET)`, so a
    # removal-mentioning word never appeared in more than ONE position and the
    # family structurally could not observe first-placement capture. QA rebuilt
    # it with a single extra leading operand and 10773 of 12016 members came
    # back COVERED. The leading operands below are benign words that MENTION a
    # removal name without being one, which is exactly the capture bait.
    leading = ("", "rm.txt", "unlink.log", "rmdir")
    out = {}
    for member in members:
        for opt in G.option_grammar_for(member):
            for _vlabel, value in G.OPTION_VALUES:
                for _form, fragment in G.option_value_forms(opt, value):
                    for lead in leading:
                        command = " ".join(x for x in
                                           (member, lead, fragment, G.TARGET)
                                           if x)
                        # MULTI-POSITION is a property of the CONSTRUCTION: a
                        # removal-mentioning word in the leading operand AND
                        # one in the option value. It is deliberately NOT read
                        # back off the analyzer, because a member the primary
                        # path correctly DENIES short-circuits at the
                        # option-value predicate before the second position is
                        # ever recorded — so an analyzer-side count would read
                        # 0 and would silently certify a family that had lost
                        # the dimension. Deleting `leading` drives this to 0
                        # and fails the criterion, which is the guard's job.
                        out[command] = out.get(command, False) or bool(lead)
    return sorted(out.items())


def _deciding_reason(command):
    """The reason of the FIRST boundary carrying the command's final verdict.

    ``analyze()['reason']`` already resolves this; reading the last boundary
    instead would key the ledger on whichever check happened to run last.
    """
    result = B.analyze(command)
    for b in result["boundaries"]:
        if b["verdict"] == result["verdict"]:
            return b["reason"]
    return result["reason"].split(":")[0]


def _laxity_key(command):
    """(reason_code, parse-derived positional_shape) — the ledger's key."""
    return (_deciding_reason(command),
            B.analyze(command)["removal_positional_shape"])


def _laxity_shapes(command):
    """(reason_code, the UNION of the shapes of EVERY co-winning boundary).

    Coverage needs the whole set, not one representative. QA iteration-4 F2
    measured the consequence of one: `cat rm.txt --qa-opt='<payload>' f` came
    back COVERED with shape `operand` supplied by a leading word that had
    nothing to do with the laxity, while the same command without that word
    came back UNLEDGERED. 10773 of 12016 control members were absorbed that
    way. An element is covered only when EVERY position that carries a removal
    name is ledgered under its reason code, so no position can borrow a
    neighbour's written proof.

    The set is now the UNION over every boundary carrying the final verdict.
    Revision 3's "the deciding boundary" silently resolved to the FIRST when
    several co-win, which is first-placement-wins moved one level up: 432 of
    27036 multi-position commands reported a strict SUBSET of what their own
    co-winning boundaries had recorded, and some reported `unclassified`
    despite a co-winner having recorded a real position.
    """
    result = B.analyze(command)
    return (_deciding_reason(command),
            tuple(result["removal_positional_shapes"]))


def _union_shapes(result):
    """The union rule, recomputed from the boundary list itself.

    Read straight off ``analyze()`` output rather than through its convenience
    field, so the witness family below can falsify the ANALYZER instead of
    comparing a value to itself.
    """
    shapes = []
    for b in result["boundaries"]:
        if b["verdict"] != result["verdict"]:
            continue
        for shape in b["positional_shapes"]:
            if shape not in shapes:
                shapes.append(shape)
    return shapes


def _covering_keys(declared, reason, shapes):
    """The declared keys covering EVERY shape, or None if any is unledgered."""
    keys = []
    for shape in shapes:
        key = next((k for k in declared
                    if reason.startswith(k[0]) and shape == k[1]), None)
        if key is None:
            return None
        keys.append(key)
    return keys


def test_ac_r02_10_predicate_is_single_sourced():
    """The hook must EXECUTE the same file the test READS. A copy in either
    consumer would make the invariant vacuous."""
    hook = open(H.HOOK, encoding="utf-8").read()
    assert "pol_degraded_removal_reference.ere" in hook
    pattern = G.degraded_removal_reference_pattern()
    assert pattern not in hook, "hook inlines a copy of the shared predicate"
    test_source = open(__file__, encoding="utf-8").read()
    generator_source = open(G.__file__, encoding="utf-8").read()
    assert pattern not in test_source and pattern not in generator_source


def test_ac_r02_10_domain_is_non_vacuous(sweeps):
    domain = _restricted_domain(sweeps)
    assert len(domain) >= 1500, len(domain)
    # Membership in the restricted domain IS the degraded denial.
    assert all(G.degraded_denies_removal_reference(c) for c in domain)


def test_ac_r02_10_laxity_is_fully_ledgered(sweeps):
    """Keyed on (reason_code, positional_shape), not reason_code alone.

    Iteration 3 keyed on the reason code by itself, so 981 elements inherited
    an entry whose justification says "it sits in OPERAND position" while none
    of them did (QA iteration-3 F2). The shape comes from the PARSER, so an
    element that reaches a ledgered code from an undeclared position now fails.
    """
    ledger = json.load(open(LEDGER_PATH, encoding="utf-8"))
    declared = {}
    for entry in ledger["entries"]:
        shape = entry["positional_shape"]
        assert shape in B.POSITIONAL_SHAPES, shape
        assert shape != B.SHAPE_UNCLASSIFIED, (
            "`unclassified` is inadmissible as a ledger key")
        assert entry["admissible_proof_kind"] in ADMISSIBLE_PROOF_KINDS, entry
        bound = PROOF_KIND_SHAPE_BOUND.get(entry["admissible_proof_kind"])
        assert bound is None or bound == shape, (
            "%s is bound to shape %s, entry declares %s"
            % (entry["admissible_proof_kind"], bound, shape))
        assert entry["representative_command"].strip()
        # The justification must NAME its own shape verbatim, so a text
        # asserting OPERAND position can never sit on a non-operand entry.
        assert shape in entry["positional_justification"], (
            "%s justification does not name its declared shape" % (entry,))
        assert not any(entry["reason_code"].startswith(bad)
                       for bad in INADMISSIBLE_REASON_CODES)
        key = (entry["reason_code"], shape)
        assert key not in declared, "duplicate ledger key %s" % (key,)
        declared[key] = entry
    assert len(declared) <= ledger["max_entries"] <= 40

    laxity = [c for c in _restricted_domain(sweeps) if G.analyze_allowed(c)]
    seen = {}
    refcount = {}
    referenced = set()
    unledgered = []
    multi_shape = 0
    for command in laxity:
        reason, shapes = _laxity_shapes(command)
        keys = _covering_keys(declared, reason, shapes)
        if keys is None:
            unledgered.append(command)
        else:
            # Counted ONCE, under the shape of the position the walk reached
            # first, so sum(members) == |L| stays exact. Coverage still needed
            # EVERY shape, which is what stops a second position from
            # inheriting the first one's written proof.
            referenced.update(keys)
            seen[keys[0]] = seen.get(keys[0], 0) + 1
            for key in keys:
                refcount[key] = refcount.get(key, 0) + 1
            if len(set(shapes)) > 1:
                multi_shape += 1

    # expect.unledgered_laxity_elements == 0, with no carve-out. Revision 3's
    # closed 13-token vocabulary could not name a heredoc body or an assignment
    # prefix, so six pinned expected_exit=0 rows were unledgerable BY ANY
    # implementation and this assertion carried a declared exemption. Revision
    # 4 added both tokens, the analyzer records them at the two sites the walk
    # already reached, and the exemption is GONE.
    assert unledgered == [], (
        "%d unledgered laxity elements; sample: %s"
        % (len(unledgered), unledgered[:6]))
    assert "pending_vocabulary_extension" not in ledger, (
        "the vocabulary extension landed in AC-R02-10 revision 4; the ledger "
        "must carry real entries, not a declared exemption")

    # ALIVE means REFERENCED through any shape in an element's set — not
    # "counted". The two notions must differ, and by exactly the number of
    # multi-shape elements: an element with two shapes references two entries
    # while being counted once, which is what keeps sum(members) == |L| exact.
    dead = sorted(set(declared) - referenced)
    assert dead == [], "dead (never-referenced) ledger entries: %s" % dead
    declared_total = sum(e["members"] for e in ledger["entries"])
    assert declared_total == len(laxity), (
        "member counts %d != |L| %d" % (declared_total, len(laxity)))
    # references - members == the number of multi-shape elements, exactly. This
    # is why the criterion states ALIVE and COUNTED separately: an entry that is
    # only ever a SECOND shape has 0 members and is still exercised by a real
    # element today, so it is not the speculative pre-declaration the cap
    # paragraph forbids.
    assert sum(refcount.values()) - declared_total == multi_shape, (
        sum(refcount.values()), declared_total, multi_shape)
    for key, entry in sorted(declared.items()):
        assert refcount.get(key, 0) >= 1, (
            "%s is declared but no element references it" % (key,))
        assert entry["referenced_by"] == refcount.get(key, 0), (
            "%s declares referenced_by %d, measured %d"
            % (key, entry["referenced_by"], refcount.get(key, 0)))
        assert seen.get(key, 0) == entry["members"], (
            "%s declares %d members, measured %d"
            % (key, entry["members"], seen.get(key, 0)))


def test_ac_r02_10_non_absorption_control_family(sweeps):
    """Regenerated at test time (a checked-in list is not a substitute).

    Members of proof kinds (3)/(4)/(5) with the removal reference moved OUT of
    operand position must be NOT-IN-L or UNLEDGERED — never COVERED. Reporting
    one as covered is precisely the absorption QA measured at iteration 3.
    """
    ledger = json.load(open(LEDGER_PATH, encoding="utf-8"))
    declared = {(e["reason_code"], e["positional_shape"]) for e in ledger["entries"]}
    control = _non_absorption_control(sweeps)
    assert len(control) >= 200, len(control)
    covered, not_in_l, unledgered = [], 0, 0
    multi_position = 0
    reported_multi_shape = 0
    for command, is_multi_position in control:
        if is_multi_position:
            multi_position += 1
        # Analyzed ONCE per member — the family is ~1.7M commands, so a second
        # pass would cost minutes.
        result = B.analyze(command)
        if len(set(_union_shapes(result))) > 1:
            reported_multi_shape += 1
        if not result["allowed"]:
            not_in_l += 1
            continue
        reason, shapes = _laxity_shapes(command)
        if _covering_keys(declared, reason, shapes) is not None:
            covered.append((command, reason, shapes))
        else:
            unledgered += 1
    assert covered == [], (
        "%d control members were ABSORBED by a ledger entry; sample: %s"
        % (len(covered), covered[:5]))
    assert not_in_l + unledgered == len(control), (
        len(control), not_in_l, unledgered)
    # A family in which no removal-mentioning word ever occupies two positions
    # is VACUOUS on the property it exists to test: revision 3's control was
    # exactly that, and QA broke the criterion by adding this one dimension.
    assert multi_position > 0, (
        "multi_position_control_members == 0; the control family cannot "
        "falsify the anti-absorption claim it certifies")
    # REPORTED for QA, and deliberately NOT asserted > 0. Every multi-position
    # member DENIES, and denial short-circuits at the option-value predicate
    # before the second position is recorded, so the analyzer-side count is
    # legitimately 0 here. That is the correct outcome — a denied member is not
    # in L at all — and it is exactly why the assertion above measures the
    # construction rather than the report.
    print("multi_position_control_members=%d of %d; analyzer_reported_multi_"
          "shape=%d; not_in_L=%d; unledgered=%d; covered=0"
          % (multi_position, len(control), reported_multi_shape,
             not_in_l, unledgered))


def test_ac_r02_10_boundary_budget_exhaustion_is_not_primary_laxity():
    """AC-R02-10's exhaustion case. The criterion grows here with the defect.

    MEASURED VIOLATION this closes: on a command of `MAX_BOUNDARIES` inert
    padding units followed by a filesystem removal, the DEGRADED predicate
    DENIED while the PRIMARY path ALLOWED (exit 0, PROVEN_INERT) — primary
    laxer than its own fallback — and that element appeared in NONE of the
    ledger's entries. AC-R02-10 was false, and its own test could not see it:
    every command in the restricted domain is short, so nothing in U ever
    exhausted the boundary budget. `MAX_BOUNDARIES`, `boundary_limit` and
    `overflow` appear ZERO times in lane r02's QA report.

    A criterion that only samples SHORT commands cannot certify a property of
    the analyzer's LONG-INPUT behaviour, so the domain is extended by shape,
    not by one more literal. The thresholds straddle the cap in both
    directions so an off-by-one cannot re-open the cliff, and the family is
    regenerated from `B.MAX_BOUNDARIES` so retuning the budget re-aims it
    rather than silently aiming it at the wrong side.

    Note this family needs NO ledger entry: after the repair the primary path
    DENIES, so it is not laxity, and the ledger's `_doc.exhaustion_case`
    records that reasoning so a later reader does not read its absence as an
    omission. An entry here would be a claim that fail-open at the budget is
    an accepted exception, which is exactly the opposite of the invariant.
    """
    removal = "rm qa-overflow-target.txt"
    for units in (B.MAX_BOUNDARIES - 1, B.MAX_BOUNDARIES,
                  B.MAX_BOUNDARIES + 1, B.MAX_BOUNDARIES * 2):
        command = " ; ".join(["echo ok"] * units + [removal])
        # In the restricted domain by the domain's own test: degraded denies.
        assert G.degraded_denies_removal_reference(command), units
        # ... and the primary path must not be laxer than it.
        assert not G.analyze_allowed(command), (
            "primary ALLOWS at %d padding units while degraded DENIES; this is "
            "the AC-R02-10 violation the boundary cap used to produce" % units)
    # The counterweight, in the same criterion: length alone must not deny.
    # A repair that satisfied the above by denying every long command would
    # trade a fail-open for a false-positive, and this catches that.
    assert G.analyze_allowed(" ; ".join(["echo ok"] * (B.MAX_BOUNDARIES - 1)))


def test_ac_r02_10_every_representative_is_actually_lax():
    ledger = json.load(open(LEDGER_PATH, encoding="utf-8"))
    for entry in ledger["entries"]:
        command = entry["representative_command"]
        assert G.analyze_allowed(command), command
        assert G.degraded_denies_removal_reference(command), command
        # The witness must EXHIBIT THAT EXACT PAIR, or the entry documents a
        # position no member of the class actually occupies. Under the union
        # rule a witness may legitimately carry several positions, so the test
        # is membership in its shape SET, not equality with its first shape:
        # `echo "$(command -v rm)"` occupies builtin_lookup_operand AND
        # operand, and demanding equality would make one of the two pairs it
        # genuinely exhibits unwitnessable.
        reason, shapes = _laxity_shapes(command)
        assert entry["positional_shape"] in shapes, (
            "%r has shapes %r, entry declares %r"
            % (command, shapes, entry["positional_shape"]))
        assert reason.startswith(entry["reason_code"]), (command, reason)


# AC-R02-10 revision 4's shape-set fidelity family. Its words MENTION a removal
# name without BEING one and its target is its own token, so no member can
# collide with anything in domain U — the family can neither enlarge L nor
# manufacture an unledgered element. It asserts the set-valued shape as an
# OBLIGATION checkable directly against the analyzer rather than as an
# implementation courtesy visible only through the ledger.
WITNESS_WORDS = ("rm.txt", "unlink.log", "rmdir.md", "shred.cfg")
WITNESS_TARGET = "qa-witness"


# The one form excluded from the family, on a STRUCTURAL ground measured
# before it was excluded, not because it failed the assertion. In
# `clustered_short` the value is CONCATENATED onto the cluster prefix, so a
# benign word fuses with it: `-abX` + `rm.txt` canonicalizes to the value
# `bXrm.txt`, whose tokens are `bXrm` and `txt` and which therefore MENTIONS no
# removal name at all. The construction's own precondition — "an option-value
# placement of a benign removal-MENTIONING word" — is not met, so those triples
# are not witnesses of anything. The fusion is benign-only: the dangerous
# counterpart `-abX/bin/rm` still yields the token `rm`, still mentions, and
# still denies, which ``_clustered_dangerous_still_denies`` asserts below so
# the exclusion cannot hide a leak.
WITNESS_EXCLUDED_FORM = "clustered_short"


def _shape_set_fidelity_witnesses():
    """(C, P1, P2) triples: a multi-position command and its two projections."""
    out = []
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        options = G.option_grammar_for(member)
        if not options:
            continue
        opt = options[0]
        for lead in WITNESS_WORDS:
            for word in WITNESS_WORDS:
                for form, fragment in G.option_value_forms(opt, word):
                    if form == WITNESS_EXCLUDED_FORM:
                        continue
                    out.append((
                        " ".join((member, lead, fragment, WITNESS_TARGET)),
                        " ".join((member, lead, WITNESS_TARGET)),
                        " ".join((member, fragment, WITNESS_TARGET))))
    return out


def test_clustered_attached_form_fuses_only_benign_words():
    """The measured ground for excluding one form from the witness family.

    If this ever stops holding — if a DANGEROUS clustered value stopped
    mentioning, or stopped denying — the exclusion above would be hiding a
    leak, and this test fails before the witness family can be read as a pass.
    """
    assert not B.text_mentions_removal_name("bXrm.txt")
    assert B.text_mentions_removal_name("bX/bin/rm")
    for member in sorted(B.INERT_ARGV_CONSUMERS):
        options = G.option_grammar_for(member)
        if not options or options[0].startswith("--"):
            continue
        fragment = "-ab%s%s" % (options[0][1:], "/bin/rm")
        command = " ".join((member, fragment, G.TARGET))
        assert not G.analyze_allowed(command), command


def test_ac_r02_10_shape_set_fidelity_witness_family(sweeps):
    """shapes(C) == shapes(P1) UNION shapes(P2), and |shapes(C)| >= 2.

    This is the property first-placement-wins and first-boundary-wins both
    break, stated so it fails against the ANALYZER rather than only showing up
    as an absorbed ledger element three steps downstream. BA measured 4671 of
    27036 constructible witnesses failing it under the first-boundary rule; it
    becomes universally true exactly when the union rule lands.
    """
    witnesses = _shape_set_fidelity_witnesses()
    assert len(witnesses) >= 200, len(witnesses)
    # OUTSIDE domain U, so it cannot enlarge L or manufacture unledgered
    # elements. Asserted, not asserted-about.
    domain = set(_restricted_domain(sweeps))
    overlap = [c for c, _p1, _p2 in witnesses if c in domain]
    assert overlap == [], overlap[:5]

    violations, thin = [], []
    for command, p1, p2 in witnesses:
        shapes = set(_union_shapes(B.analyze(command)))
        expected = (set(_union_shapes(B.analyze(p1)))
                    | set(_union_shapes(B.analyze(p2))))
        if shapes != expected:
            violations.append((command, sorted(shapes), sorted(expected)))
        if len(shapes) < 2:
            thin.append((command, sorted(shapes)))
    assert violations == [], (
        "%d witnesses whose shape set is not the union of their projections'; "
        "sample: %s" % (len(violations), violations[:5]))
    assert thin == [], (
        "%d witnesses reporting fewer than 2 positions; sample: %s"
        % (len(thin), thin[:5]))


def test_ac_r02_10_only_co_winning_boundaries_contribute_shapes():
    """The DECIDING-VERDICT half of the witness: a losing boundary's position
    may not appear.

    Without it the union rule would be a licence to collect every position in
    the command, and a benign operand's `operand` shape could key the ledger
    for a command whose verdict came from somewhere else entirely.
    """
    for command in ("echo rm.txt; /bin/rm qa-target",
                    "cat rm.txt && /bin/rm -rf qa-target",
                    "printf %s unlink.log; unlink qa-target"):
        result = B.analyze(command)
        assert not result["allowed"], command
        # What the ANALYZER reports, not what the test recomputes.
        reported = set(result["removal_positional_shapes"])
        co_winning = set(_union_shapes(result))
        losing_only = {s for b in result["boundaries"]
                       if b["verdict"] != result["verdict"]
                       for s in b["positional_shapes"]} - co_winning
        # `unclassified` is the reserved TOTALITY fallback, used exactly when
        # the union is empty. These commands DENY, so they never enter L and
        # its inadmissibility as a ledger key is never reached.
        assert reported == (co_winning or {B.SHAPE_UNCLASSIFIED}), (
            command, reported, co_winning)
        assert not (reported & losing_only), (command, reported, losing_only)
        # Concretely: the benign leading word sits on a PROVEN_INERT boundary
        # that did NOT carry the verdict, so its `operand` position must not
        # be available to key the ledger for this command.
        assert losing_only, (
            "%r has no losing-boundary position, so it cannot witness the "
            "exclusion" % command)
        assert B.SHAPE_OPERAND not in reported, (command, sorted(reported))


@pytest.mark.parametrize("mode", ["timeout", "module_unreadable", "crash"])
def test_ac_r02_10_degradation_modes_deny_the_adversarial_domain(mode, tmp_path):
    """Three distinct analyzer-failure modes, each denying a removal-suspect
    sample end to end through the hook."""
    env = dict(os.environ)
    if mode == "timeout":
        env["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = "0.001s"
    elif mode == "module_unreadable":
        env["CLAUDE_HOOK_BOUNDARY_MEM_KB"] = "2048"
    else:
        env["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = "0s"
    sample = list(ITERATION2_COUNTER_EXAMPLES)[:8] + [
        "man -P '/bin/rm -rf T' ls", "taskset 0x1 /bin/r? -rf T"]
    for command in sample:
        code, _out, err = H.run_hook_command(command, env=env)
        assert code == 2, "%s allowed under %s" % (command, mode)
        assert err.strip()


# ---------------------------------------------------------------------------
# Named denial controls: the 23 iteration-2 counter-examples and the 12
# predev adversarial probes. These are FLOORS, not the generality evidence.
# ---------------------------------------------------------------------------

ITERATION2_COUNTER_EXAMPLES = (
    # F1 — option-value execution facilities of authorizing-table members
    "man -P '/bin/rm -rf /tmp/qa-target-A' ls",
    "man --pager=/bin/rm ls",
    "sort --compress-program=/bin/rm /var/log/big.txt",
    "split --filter='/bin/rm -rf /tmp/qa-target-B' data.txt",
    "sdiff --diff-program=/bin/rm a b",
    "diff3 --diff-program=/bin/rm a b c",
    "rg --pre /bin/rm needle .",
    "rg --pre /bin/r? needle .",
    "compgen -C '/bin/rm -rf /tmp/qa-target-C' -- f",
    # F2 — unexpanded head representations behind one unmodelled wrapper
    "taskset 0x1 /bin/{rm,ls} /tmp/qa-t",
    "taskset 0x1 /bin/{r,}m /tmp/qa-t",
    "taskset 0x1 /bin/rm* /tmp/qa-t",
    "taskset 0x1 /bin/r? /tmp/qa-t",
    "taskset 0x1 $'rm' /tmp/qa-t",
    "taskset 0x1 $'\\x72m' /tmp/qa-t",
    # F3 — assignment prefixes that are documented exec vectors
    "GIT_EXTERNAL_DIFF='/bin/rm -rf /tmp/qa-t' git diff",
    "GIT_PAGER='/bin/rm -rf /tmp/qa-t' git log",
    "GIT_SSH_COMMAND='/bin/rm -rf /tmp/qa-t' git fetch",
    "PAGER='/bin/rm -rf /tmp/qa-t' man ls",
    "LESSOPEN='|/bin/rm %s' less f.txt",
    "EDITOR=/bin/rm git commit",
    # F4 — keyword-blind payload position
    "capsh -- -c 'if true; then /bin/rm -rf /tmp/qa-t; fi'",
    # F5 — interpreter dynamic attribute access (leaked on BOTH paths)
    'python3 -c \'import os; getattr(os,"remove")("/tmp/qa-t")\'',
)

REP_PROBES = {
    "POL-RD-REP-01-coproc-body": "coproc QAJOB /bin/rm qa-probe-1",
    "POL-RD-REP-02-plus-O-arity": "bash +O extglob -c '/bin/rm qa-probe-2'",
    "POL-RD-REP-03-flock-c-payload": "flock -n 9 -c '/bin/rm qa-probe-3'",
    "POL-RD-REP-04-parallel-template":
        "parallel --rpl '{x} s/.//' /bin/rm ::: qa-probe-4",
    "POL-RD-REP-05-git-alias-dispatch":
        "git -c alias.qawipe='!command /bin/rm' qawipe qa-probe-5",
    "POL-RD-REP-06-container-payload": "docker exec qa-c sh -c '/bin/rm qa-probe-6'",
    "POL-RD-REP-07-generated-code":
        "python3 -c 'import os; os.system(\"/bin/rm qa-probe-7\")'",
    "POL-RD-REP-08-prompt-reexpansion": "X='$(/bin/rm qa-probe-8)'; echo \"${X@P}\"",
    "POL-RD-REP-09-xargs-abbreviation": "printf qa | xargs --max-p 1 /bin/rm",
    "POL-RD-REP-10-ssh-payload": "ssh qa-host sh -c '/bin/rm qa-probe-10'",
    "POL-RD-REP-11-at-stdin-payload": "at now <<< '/bin/rm qa-probe-11'",
    "POL-RD-REP-12-heredoc-line-joining": "cat <<EOF\n$\\\n(/bin/rm qa-probe-12)\nEOF",
}


# QA iteration-3's minimal reproduction, verbatim. The second command is
# strictly more dangerous than the first and was the one that ALLOWED.
ITERATION3_COUNTER_EXAMPLES = (
    "cat --qa-opt=/bin/rm f",
    "cat --qa-opt='/bin/rm -rf qa-target' f",
    "cat -X'/bin/rm -rf qa-target' f",
    "cat -abX'/bin/rm -rf qa-target' f",
    "cat -abXrm qa-target",
    "cat -X/bin/r? qa-target",
    "man --pager='/bin/rm -rf qa-target' ls",
    "sort --compress-program='/bin/rm -rf qa-target' f",
)


@pytest.mark.parametrize("command", ITERATION2_COUNTER_EXAMPLES)
def test_iteration2_counter_examples_deny(command):
    assert not G.analyze_allowed(command), G.analyze_reason(command)


@pytest.mark.parametrize("command", ITERATION3_COUNTER_EXAMPLES)
def test_iteration3_counter_examples_deny(command):
    assert not G.analyze_allowed(command), G.analyze_reason(command)


@pytest.mark.parametrize("command", ITERATION3_COUNTER_EXAMPLES)
def test_iteration3_counter_examples_deny_through_the_hook(command):
    """Through the shipped hook, not only in process: QA confirmed the leak at
    exit-code level (exit 2 vs exit 0), so the fix is confirmed there too."""
    code, _out, err = H.run_hook_command(command)
    assert code == 2, command
    assert err.strip()


@pytest.mark.parametrize("probe_id,command", sorted(REP_PROBES.items()))
def test_rep_probes_deny(probe_id, command):
    assert not G.analyze_allowed(command), probe_id


def test_inadmissible_reason_code_is_absent_from_the_analyzer():
    source = open(B.__file__, encoding="utf-8").read()
    for bad in INADMISSIBLE_REASON_CODES:
        assert '"%s"' % bad not in source, (
            "%s is still emitted as a boundary reason" % bad)


# ---------------------------------------------------------------------------
# AC-R02-16 — harness fidelity: the in-process sweeps must be measuring the
# SHIPPED decision path.
# ---------------------------------------------------------------------------

FIDELITY_PER_SWEEP = 100


def _fidelity_pools(sweeps):
    return {
        "installed": sweeps["installed"],
        "option_position": [c for c, _m, _o in sweeps["option_probes"]],
        "shell_forms": sweeps["forms"],
        "interpreter": sweeps["interp"],
        "benign": G.benign_sweep(),
        "fixture_and_controls": (
            [r["command"] for r in H.load_fixture()["rows"]]
            + list(ITERATION2_COUNTER_EXAMPLES) + list(REP_PROBES.values())),
    }


# Hook rules that are NOT the removal policy. AC-R02-07 requires their
# behaviour unchanged, and a denial they issue says nothing about whether the
# in-process harness measures the removal decision path. Attributed explicitly
# rather than ignored: a disagreement must be EXPLAINED by one of these, and
# the attributed set is asserted small so it cannot become a silent sink.
NON_REMOVAL_GUARDS = ("protected-runtime-guard",)


def test_ac_r02_16_seeded_sample_agrees_with_the_real_hook(sweeps):
    pools = _fidelity_pools(sweeps)
    disagreements = []
    attributed = []
    sampled = 0
    for name, pool in sorted(pools.items()):
        sample = G.seeded_sample(pool, FIDELITY_PER_SWEEP, name)
        for command in sample:
            sampled += 1
            in_process = G.analyze_allowed(command)
            code, _out, err = H.run_hook_command(command)
            if bool(code == 0) == in_process:
                continue
            guard = next((g for g in NON_REMOVAL_GUARDS if g in err), None)
            if guard is not None and code == 2 and in_process:
                attributed.append((name, command, guard))
            else:
                disagreements.append((name, command, code, in_process))
    assert sampled >= 600, sampled
    assert disagreements == [], disagreements[:10]
    # The escape hatch must stay narrow: if a large share of the sample were
    # explained away, the fidelity property would be measuring nothing.
    assert len(attributed) <= max(5, sampled // 100), attributed[:10]


def test_ac_r02_16_sample_is_reproducible(sweeps):
    a = G.seeded_sample(sweeps["forms"], FIDELITY_PER_SWEEP, "shell_forms")
    b = G.seeded_sample(sweeps["forms"], FIDELITY_PER_SWEEP, "shell_forms")
    assert a == b and len(a) == FIDELITY_PER_SWEEP
    assert G.FIDELITY_SEED == 20260820


# ---------------------------------------------------------------------------
# Degraded-predicate deployment is itself fail-closed.
# ---------------------------------------------------------------------------

def test_missing_degraded_predicate_file_denies(tmp_path):
    """A hook deployment whose shared predicate is gone must not fall through."""
    import shutil
    stage = tmp_path / "hooks"
    shutil.copytree(os.path.join(G.REPO_ROOT, "hooks"), stage,
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    os.remove(stage / "lib" / "pol_degraded_removal_reference.ere")
    os.remove(stage / "lib" / "bash_execution_boundary.py")
    code, _out, err = H.run_hook_command("man rm", hook=str(stage / "pretool-bash-safety.sh"))
    assert code == 2 and "FAIL-CLOSED" in err
