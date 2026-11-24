"""The owner's rule for a command the removal policy cannot prove safe (lib/bash_safety_rules.py::removal_policy).

The rule (owner, 2026-11-19): when the guard cannot prove a command safe, it refuses if a removal word, by the single
definition in lib/pol_degraded_removal_reference.ere, is in the text that can become the command, and otherwise lets
the command run and hands one entry to the record. A removal the analyzer finds (FORBIDDEN_REMOVAL) is refused as before.

"Cannot prove" has two forms and two rules: the analyzer answers UNRESOLVED (the primary path: the word list is asked
of the analyzer's unresolved_scopes, the text that can become each command it left unresolved), or it gives no usable
verdict (timeout, memory ceiling, crash: the degraded path: the word list is asked of the whole text).
hooks/tests/test_removal_policy_parsed_rule.py holds the text-only shapes that run on the primary path alone. Before this rule every UNRESOLVED command was
refused, also when its text held no removal word: a variable assigned inside a loop, a program name held in a
variable, inline Python, a pattern with wildcard characters. The commands below are those shapes, written with
neutral names. No command is ever executed: each is data handed to the hook or the policy.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))
sys.path.insert(0, HERE)

import bash_execution_boundary as eb  # noqa: E402
import pol_replay_harness as H  # noqa: E402
import pol_sweep_generators as G  # noqa: E402

# bash_safety_rules takes its hooks directory from sys.argv[1], which under pytest is a test path.
_argv, sys.argv = sys.argv, [sys.argv[0], HOOKS_DIR]
try:
    import bash_safety_rules as R  # noqa: E402
finally:
    sys.argv = _argv
R.HOOKS, R.LIB = HOOKS_DIR, os.path.join(HOOKS_DIR, "lib")

DEGRADED_ENV = {"timeout": {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "0.001s"}, "memory": {"CLAUDE_HOOK_BOUNDARY_MEM_KB": "4096"}}
# The primary path gives the analyzer time: on a loaded host its 15 s default can pass, and that is the other path.
PRIMARY_ENV = {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "120s"}
MODE_ENV = {"primary": PRIMARY_ENV, **DEGRADED_ENV}
PRIMARY_REFUSAL = "removal-policy — UNRESOLVED"
DEGRADED_REFUSAL = "removal-policy FAIL-CLOSED"

# Unproven, no removal word: one group per reason the analyzer gives for not proving such a command.
UNPROVEN_NO_REMOVAL_WORD = [
    # dynamic_command_head: an assignment inside a loop or a branch, read as a program name
    "for a in x y; do n=$(ls $a | wc -l); echo $n; done",
    "for n in 01 02; do f=docs/part-$n.json; ls -la $f; done",
    "x=1; if [ $x -gt 0 ]; then y=$((x+1)); echo $y; fi",
    "while read l; do n=$(echo $l | wc -c); echo $n; done < f.txt",
    # dynamic_command_head: a program name held in a variable
    "PY=venv/bin/python; $PY --version",
    "for py in python3 venv/bin/python; do $py --version; done",
    "R=tools/query.sh; $R \"\\d t1\"; $R \"\\d t2\"",
    "$TOOL --version",
    # interpreter_expansion_changes_program: inline Python holding a shell variable
    "for f in a.json b.json; do python3 -c \"import json; print(json.load(open('$f')))\"; done",
    "H=/srv/app; for f in a b; do python3 -c \"import json; print(json.load(open('$H/$f.json')))\"; done",
    # interpreter_dynamic_attribute_access: inline Python that looks a name up
    "python3 -c \"import importlib.metadata as m; print(m.version('pytest'))\"",
    # dynamic_git_subcommand: a git argument holding a variable or a substitution
    "for g in /srv/a/.git /srv/b/.git; do git --git-dir=\"$g\" rev-parse --is-bare-repository; done",
    "git --git-dir=$(cat where.txt) log -1 --format=%h",
    "S=status; git $S --short",
    # option_value_removal_reference: an option or a quoted word the analyzer misreads
    "du -s -BM /srv/data/* | sort -rn | head",
    "echo \"--- stdout ($(wc -l < run.stdout) lines)\"",
    # unproven_boundary_with_removal_reference: a pattern, a loop variable or a substitution handed to sed, git
    # grep, git show, curl, gh, mkdir or a shell function
    "for t in a/x b/y; do find $t -type f | sed \"s|$t/||\" | sort | head; done",
    "ls scripts | head; sed -n 1,60p scripts/$(ls scripts | grep -i -E \"alpha|beta\" | head -1)",
    "git grep -n \"alpha_x\\|beta_y\\|\\.method(\\|input\\[.key.\\]\" -- ':!tests' | cut -c1-230",
    "for f in a.py b.py; do git show \"HEAD:src/$f\" | sha256sum; done",
    "for s in a b; do curl -s -m 20 \"https://example.com/api?s=${s}&f=x&h&e=csv\"; echo; done",
    "gh run list --limit 5 --json databaseId,status --jq '.[] | [.databaseId,.status[0:10],(.conclusion//\"-\")] | @tsv'",
    "mkdir -p \"out/$(date +%F)\" && ls out",
    "sha(){ sha256sum \"$1\" | cut -d' ' -f1; }; for f in a.json b.json; do echo $f $(sha data/$f); done",
    # find_operand_removal_reference, wrapper_arity_mismatch, census_fatal
    "for d in a b; do find \"/srv/$d\" -maxdepth 1 -type f | wc -l; done",
    "E=tools; for p in a b; do /usr/bin/time -f \"$p %es\" python3 $E/$p.py --help >/dev/null; done",
    "f=docs/a.md; echo \"count: $(grep -c '^```' $f) (two lines)\"; wc -l $f",
    # Words that only resemble a removal word: the single definition decides, not a substring.
    "$TOOL removed", "$TOOL rmx form", "$TOOL rm_backup undeleted",
]

# Unproven, and the text holds a removal word: refused on both paths.
UNPROVEN_WITH_REMOVAL_WORD = [
    "x=rm; $x -r build",
    "$TOOL remove pkg",
    "$CLEANER --delete old",
    "PY=venv/bin/python; $PY tools/rm.py",
    "for f in a b; do git rm \"$f\"; done",
]

# Unproven, and the removal word is only text (an echo's argument, after a sourced file): the primary path reads
# the command and lets it run; the degraded path, which reads nothing, refuses it.
UNPROVEN_TEXT_ONLY = ["for d in a b; do t=$d/x; echo \"rmdir $t\"; done", "source ./env.sh; echo unlink"]

# A removal the analyzer finds: the named prohibition. The last three name no removal word in their raw text.
FORBIDDEN_REMOVALS = [
    "rm -rf build", "find . -name '*.tmp' -delete", "git rm -f x", "for f in a b; do rm \"$f\"; done",
    "r''m -rf build", "un''link x", "find . -name x -de''lete",
    # Python read with ast (they were unproven and refused on their text before)
    "python3 -c 'import shutil; shutil.rmtree(\"build\")'", "python3 -c 'import os; getattr(os, \"remove\")(\"x\")'",
]

# Proven by the analyzer although the text holds a removal word.
PROVEN_WITH_REMOVAL_WORD = ["man rm", "grep -rn rm README.md", "git rm --cached x", "echo \"$(printf %s rm)\""]
PROVEN_PLAIN = ["ls -la", "git status --short", "m=0; m=$((m+1)); echo $m"]


def holds_removal_word(command):
    """The single definition, read from its file (never copied here)."""
    return G.degraded_denies_removal_reference(command)


def removal_words():
    """The words of the single definition, read out of its file."""
    words = max((group.split("|") for group in re.findall(r"\(([A-Za-z_|]+)\)", G.degraded_removal_reference_pattern())),
                key=len)
    assert len(words) >= 10, words
    return words


def generated_unproven():
    """Every removal word of the definition in an unproven command, and beside each a word that only resembles it."""
    named, unnamed = [], []
    for k, word in enumerate(removal_words()):
        shape = ("$TOOL %s y", "for f in a b; do t=$f; echo %s $t; done")[k % 2]
        named.append(shape % word)
        unnamed.append(shape % (("x" + word, word + "x")[k % 2]))
    return named, unnamed


def policy(command, degraded=False):
    """removal_policy() alone, in this process: (refused, entry, stderr text of the refusal)."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    saved, real = os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT"), sys.stderr
    os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = "0.001s" if degraded else PRIMARY_ENV["CLAUDE_HOOK_BOUNDARY_TIMEOUT"]
    sys.stderr = err = io.StringIO()
    try:
        return False, R.removal_policy(payload, command), ""
    except SystemExit as exc:
        assert exc.code == 2, exc.code
        return True, None, err.getvalue()
    finally:
        sys.stderr = real
        os.environ.pop("CLAUDE_HOOK_BOUNDARY_TIMEOUT", None)
        if saved is not None:
            os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = saved


def run_hook(command, hook=H.HOOK, **env_extra):
    code, _out, err = H.run_hook_command(command, hook=hook, env={**os.environ, **env_extra})
    return code, err


@pytest.fixture(scope="module")
def hook_runs():
    """Every corpus command through the real hook on the primary path and under each degraded mode, run once."""
    commands = (UNPROVEN_NO_REMOVAL_WORD + UNPROVEN_WITH_REMOVAL_WORD + UNPROVEN_TEXT_ONLY + FORBIDDEN_REMOVALS
                + PROVEN_WITH_REMOVAL_WORD + PROVEN_PLAIN)
    jobs = [(c, mode) for c in commands for mode in ["primary"] + sorted(DEGRADED_ENV)]
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda job: run_hook(job[0], **MODE_ENV[job[1]]), jobs))
    return dict(zip(jobs, results))


# ── The corpus is what the rule is about ─────────────────────────────────────

def test_the_corpus_is_unproven_by_the_live_analyzer_and_split_by_the_single_definition():
    assert not [c for c in UNPROVEN_NO_REMOVAL_WORD if holds_removal_word(c)]
    assert not [c for c in UNPROVEN_WITH_REMOVAL_WORD if not holds_removal_word(c)]
    for command in UNPROVEN_WITH_REMOVAL_WORD + UNPROVEN_TEXT_ONLY:
        assert holds_removal_word(command)
    for command in UNPROVEN_WITH_REMOVAL_WORD:
        assert eb.analyze(command)["verdict"] == eb.UNRESOLVED, command
    # An analyzer that learns to prove some of the first list leaves the rule nothing to decide for those; the list
    # must still be mostly unproven, or these tests no longer exercise the rule.
    unproven = [c for c in UNPROVEN_NO_REMOVAL_WORD if eb.analyze(c)["verdict"] == eb.UNRESOLVED]
    assert len(unproven) * 2 >= len(UNPROVEN_NO_REMOVAL_WORD), (len(unproven), len(UNPROVEN_NO_REMOVAL_WORD))
    for command in FORBIDDEN_REMOVALS:
        assert eb.analyze(command)["verdict"] == eb.FORBIDDEN_REMOVAL, command
    assert [c for c in FORBIDDEN_REMOVALS if not holds_removal_word(c)], "no removal the raw text does not name"
    for command in PROVEN_WITH_REMOVAL_WORD + PROVEN_PLAIN:
        assert eb.analyze(command)["allowed"] is True, command
    assert all(holds_removal_word(c) for c in PROVEN_WITH_REMOVAL_WORD)


# ── Through the hook ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", UNPROVEN_NO_REMOVAL_WORD)
def test_an_unproven_command_holding_no_removal_word_runs_on_the_primary_path(hook_runs, command):
    code, err = hook_runs[(command, "primary")]
    assert code == 0 and "removal-policy" not in err, (command, err)


@pytest.mark.parametrize("mode", sorted(DEGRADED_ENV))
@pytest.mark.parametrize("command", UNPROVEN_NO_REMOVAL_WORD)
def test_an_unproven_command_holding_no_removal_word_runs_on_the_degraded_path(hook_runs, mode, command):
    code, err = hook_runs[(command, mode)]
    assert code == 0 and "removal-policy" not in err, (mode, command, err)


@pytest.mark.parametrize("command", UNPROVEN_WITH_REMOVAL_WORD)
def test_an_unproven_command_holding_a_removal_word_is_refused_on_the_primary_path(hook_runs, command):
    code, err = hook_runs[(command, "primary")]
    assert code == 2 and PRIMARY_REFUSAL in err, (command, err)
    assert "a command it could not resolve holds a removal word" in err, err


@pytest.mark.parametrize("command", UNPROVEN_TEXT_ONLY)
def test_an_unproven_command_whose_removal_word_is_only_text_runs_on_the_primary_path(hook_runs, command):
    code, err = hook_runs[(command, "primary")]
    assert code == 0 and "removal-policy" not in err, (command, err)


@pytest.mark.parametrize("mode", sorted(DEGRADED_ENV))
@pytest.mark.parametrize("command", UNPROVEN_WITH_REMOVAL_WORD + UNPROVEN_TEXT_ONLY
                         + [c for c in FORBIDDEN_REMOVALS if holds_removal_word(c)] + PROVEN_WITH_REMOVAL_WORD)
def test_a_command_holding_a_removal_word_is_refused_on_the_degraded_path(hook_runs, mode, command):
    code, err = hook_runs[(command, mode)]
    assert code == 2 and DEGRADED_REFUSAL in err, (mode, command, err)


@pytest.mark.parametrize("command", FORBIDDEN_REMOVALS)
def test_a_removal_the_analyzer_finds_is_refused_whatever_the_text_holds(hook_runs, command):
    """The named prohibition: FORBIDDEN_REMOVAL does not go through the rule for unproven commands."""
    code, err = hook_runs[(command, "primary")]
    assert code == 2 and "removal-policy — FORBIDDEN_REMOVAL" in err, (command, err)


@pytest.mark.parametrize("command", PROVEN_WITH_REMOVAL_WORD + PROVEN_PLAIN)
def test_a_proven_command_still_passes(hook_runs, command):
    code, err = hook_runs[(command, "primary")]
    assert code == 0 and "removal-policy" not in err, (command, err)


# ── The primary path refuses an unproven command only where the degraded path does too ────────────

def scopes_name_removal(command):
    """The primary path's question: does the text that can become an unresolved command hold a removal word?"""
    scopes = eb.analyze(command).get("unresolved_scopes") or []
    return any(G.degraded_denies_removal_reference(t) for t in scopes)


def test_on_an_unproven_command_the_primary_path_asks_the_word_list_of_its_scopes_and_the_degraded_path_of_the_text():
    """Two rules, not one (owner, 2026-11-19): the primary path refuses an unproven command exactly when its
    unresolved_scopes hold a removal word, the degraded path exactly when its text does. Each scope is text of the
    command, so the primary path never refuses what the degraded path lets run."""
    named, unnamed = generated_unproven()
    corpus = UNPROVEN_NO_REMOVAL_WORD + UNPROVEN_WITH_REMOVAL_WORD + UNPROVEN_TEXT_ONLY + named + unnamed
    assert len(named) >= 10 and len(unnamed) >= 10
    wrong, let_through, refused, text_only = [], 0, 0, 0
    for command in corpus:
        if eb.analyze(command)["verdict"] != eb.UNRESOLVED:
            continue  # proven, or a removal found: nothing for the rule to decide
        p_refused, p_entry, p_err = policy(command)
        d_refused, d_entry, d_err = policy(command, degraded=True)
        if p_refused != scopes_name_removal(command) or d_refused != holds_removal_word(command) \
                or p_refused and not d_refused:
            wrong.append((command, p_refused, d_refused))
            continue
        if p_refused:
            refused += 1
            assert PRIMARY_REFUSAL in p_err and DEGRADED_REFUSAL in d_err, (command, p_err, d_err)
        else:
            let_through += 1
            text_only += d_refused
            assert p_entry["path"] == "primary" and p_entry["reason"].startswith("UNRESOLVED "), p_entry
            assert {p_entry["rule"], p_entry["kind"]} == {"removal-policy", "let_through_unproven"}
    assert not wrong, wrong[:10]
    assert let_through >= 30 and refused >= 10 and text_only >= 5, (let_through, refused, text_only)


def test_inside_the_removal_reference_domain_the_primary_path_lets_run_only_what_its_scopes_do_not_name():
    """Over the generated shell forms that hold a removal word: the degraded path denies every one; the primary path
    allows a form only when the analyzer proved it, or left it unresolved with no removal word in any scope."""
    named, _unnamed = generated_unproven()
    forms = [c for c in G.shell_form_sweep() if holds_removal_word(c)]
    assert len(forms) >= 500, len(forms)
    domain = (UNPROVEN_WITH_REMOVAL_WORD + named + PROVEN_WITH_REMOVAL_WORD
              + [c for c in FORBIDDEN_REMOVALS if holds_removal_word(c)] + G.seeded_sample(forms, 30, "unproven-rule"))
    proven = 0
    for command in domain:
        assert holds_removal_word(command), command
        d_refused, d_entry, _err = policy(command, degraded=True)
        assert d_refused and d_entry is None, command  # the degraded path denies the whole domain
        p_refused, p_entry, _err = policy(command)
        verdict = eb.analyze(command)["verdict"]
        if p_entry is not None:
            assert verdict == eb.UNRESOLVED and not scopes_name_removal(command), command
        elif not p_refused:
            proven += 1
            assert verdict in (eb.PROVEN_INERT, eb.PROVEN_SAFE_REMOVAL), command
    assert proven >= len(PROVEN_WITH_REMOVAL_WORD)


# ── The pinned 436-row matrix ────────────────────────────────────────────────

def test_the_matrix_rows_the_rule_lets_run_are_exactly_the_unproven_ones_holding_no_removal_word():
    """The fixture pins rows at exit 2 that the rule lets run. pol_replay_harness.OWNER_RULE_LET_THROUGH
    lists them by id; this derives the same set from the rule, so the list can neither grow nor shrink by hand."""
    rows = H.load_fixture()["rows"]
    by_rule = {r["id"] for r in rows if r["expected_hook_exit_code"] == 2
               and eb.analyze(r["command"])["verdict"] == eb.UNRESOLVED and not scopes_name_removal(r["command"])}
    assert by_rule == set(H.OWNER_RULE_LET_THROUGH)
    assert all(H.expected_exit(r) == r["expected_hook_exit_code"] for r in rows if r["id"] not in by_rule)
    assert all(H.expected_exit(r) == 0 for r in rows if r["id"] in by_rule)
    # A removal the analyzer finds stays pinned at exit 2, whether or not its text names it.
    found = [r for r in rows if eb.analyze(r["command"])["verdict"] == eb.FORBIDDEN_REMOVAL]
    assert len(found) >= 250 and all(H.expected_exit(r) == 2 for r in found)
    assert [r for r in found if not holds_removal_word(r["command"])]


def test_the_matrix_rows_the_rule_lets_run_do_run_through_the_hook():
    rows = [r for r in H.load_fixture()["rows"] if r["id"] in H.OWNER_RULE_LET_THROUGH]
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda r: H.run_hook_payload(r["stdin_envelope"], env={**os.environ, **PRIMARY_ENV}), rows))
    refused = [(r["id"], r["command"], err) for r, (code, _out, err) in zip(rows, results) if code != 0]
    assert not refused, refused


# ── The rule itself, whatever the analyzer can prove today ───────────────────

class _Analyzer:
    """Stands in for the analyzer's process: a fixed answer, or a failure."""

    def __init__(self, monkeypatch, verdict=None, allowed=False, reason="some_reason:detail", returncode=0, stdout=None,
                 raises=None):
        self.calls = 0
        out = stdout if stdout is not None else json.dumps(
            {"schema": "bash-execution-boundary.v1", "verdict": verdict, "allowed": allowed, "reason": reason})

        def run(argv, **kwargs):
            self.calls += 1
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(argv, returncode, out, "")
        monkeypatch.setattr(R.subprocess, "run", run)


def _answer(command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    real, sys.stderr = sys.stderr, io.StringIO()
    try:
        return R.removal_policy(payload, command), ""
    except SystemExit as exc:
        assert exc.code == 2
        return "REFUSED", sys.stderr.getvalue()
    finally:
        sys.stderr = real


NO_VERDICT = [
    {"returncode": 3}, {"stdout": "not json"}, {"stdout": "{}"}, {"verdict": "SOMETHING_ELSE"},
    {"verdict": "UNRESOLVED", "allowed": True},  # an answer that contradicts itself is no answer
    {"raises": subprocess.TimeoutExpired("analyzer", 15)}, {"raises": OSError("cannot start")},
    {"raises": MemoryError()},
]


def test_unresolved_without_a_removal_word_is_let_run_and_names_its_reason(monkeypatch):
    _Analyzer(monkeypatch, "UNRESOLVED", reason="dynamic_command_head:$TOOL")
    entry, _err = _answer("$TOOL --version")
    assert entry == {"rule": "removal-policy", "kind": "let_through_unproven", "path": "primary",
                     "reason": "UNRESOLVED dynamic_command_head:$TOOL"}


def test_unresolved_with_a_removal_word_is_refused(monkeypatch):
    _Analyzer(monkeypatch, "UNRESOLVED", reason="dynamic_command_head:$TOOL")
    entry, err = _answer("$TOOL remove pkg")
    assert entry == "REFUSED" and "BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:$TOOL" in err, err


@pytest.mark.parametrize("answer", NO_VERDICT, ids=[str(sorted(a))[:40] + str(i) for i, a in enumerate(NO_VERDICT)])
def test_no_usable_verdict_asks_the_same_question(monkeypatch, answer):
    _Analyzer(monkeypatch, **answer)
    entry, _err = _answer("$TOOL --version")
    assert entry == {"rule": "removal-policy", "kind": "let_through_unproven", "path": "degraded",
                     "reason": "NO_VERDICT analyzer unavailable or gave no usable verdict"}
    entry, err = _answer("$TOOL remove pkg")
    assert entry == "REFUSED" and "BLOCKED: " + DEGRADED_REFUSAL in err, err
    # A plain command is no exception: without a verdict, a removal word in its text refuses it.
    assert _answer("ls -la")[0]["path"] == "degraded"
    assert _answer("man rm")[0] == "REFUSED"


def test_a_removal_the_analyzer_finds_is_refused_even_when_the_text_names_none(monkeypatch):
    _Analyzer(monkeypatch, "FORBIDDEN_REMOVAL", reason="filesystem_removal:rm")
    entry, err = _answer("r''m -rf build")
    assert not holds_removal_word("r''m -rf build")
    assert entry == "REFUSED" and "BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm" in err, err
    assert "its text holds a removal word" not in err


@pytest.mark.parametrize("verdict", ["PROVEN_INERT", "PROVEN_SAFE_REMOVAL"])
def test_a_proven_command_passes_with_nothing_for_the_record(monkeypatch, verdict):
    _Analyzer(monkeypatch, verdict, allowed=True)
    assert _answer("man rm") == (None, "")
    assert _answer("ls -la") == (None, "")


@pytest.mark.parametrize("verdict", ["PROVEN_INERT", "PROVEN_SAFE_REMOVAL"])
def test_a_proven_verdict_that_does_not_allow_stays_refused(monkeypatch, verdict):
    _Analyzer(monkeypatch, verdict, allowed=False)
    assert _answer("ls -la")[0] == "REFUSED"


# ── A missing definition refuses whatever is unproven ────────────────────────

@pytest.fixture(scope="module")
def hooks_without_the_definition(tmp_path_factory):
    stage = tmp_path_factory.mktemp("no-definition") / "hooks"
    shutil.copytree(HOOKS_DIR, stage, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    os.remove(stage / "lib" / "pol_degraded_removal_reference.ere")
    return str(stage / "pretool-bash-safety.sh")


@pytest.mark.parametrize("mode", ["primary"] + sorted(DEGRADED_ENV))
def test_without_the_definition_an_unproven_command_is_refused(hooks_without_the_definition, mode):
    code, err = run_hook("$TOOL --version", hook=hooks_without_the_definition, **MODE_ENV[mode])
    assert code == 2 and DEGRADED_REFUSAL in err and "missing or empty" in err, (mode, err)


def test_without_the_definition_the_analyzer_still_decides_what_it_can(hooks_without_the_definition):
    assert run_hook("ls -la", hook=hooks_without_the_definition, **PRIMARY_ENV)[0] == 0
    code, err = run_hook("rm -rf build", hook=hooks_without_the_definition, **PRIMARY_ENV)
    assert code == 2 and "FORBIDDEN_REMOVAL" in err, err


# ── The seam for the record ──────────────────────────────────────────────────

# decide() as the hook's process runs it, with let_through_unproven() replaced by a recorder. Prints one JSON line.
_DECIDE = r"""
import json, os, sys
hooks = sys.argv[1]
sys.path.insert(0, os.path.join(hooks, "lib"))
out = os.fdopen(os.dup(1), "w")
os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
sys.stdout = open(os.devnull, "w")
import bash_safety_rules as R
calls = []
R.let_through_unproven = lambda entry, payload: calls.append({"entry": entry, "payload": payload})
try:
    verdict, code = R.decide(sys.stdin.read()), 0
except SystemExit as exc:
    verdict, code = None, exc.code
out.write(json.dumps({"verdict": verdict, "code": code, "calls": calls}) + "\n")
"""


def decide(command, **env_extra):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "unproven-rule"}
    proc = subprocess.run([sys.executable, "-c", _DECIDE, HOOKS_DIR], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=H.REPO_ROOT, env={**os.environ, **env_extra}, timeout=120)
    assert proc.stdout.strip(), proc.stderr
    return json.loads(proc.stdout), payload, proc.stderr


@pytest.mark.parametrize("mode", ["primary"] + sorted(DEGRADED_ENV))
def test_the_seam_is_called_once_for_an_unproven_command_that_runs(mode):
    result, payload, _err = decide("PY=venv/bin/python; $PY --version", **MODE_ENV[mode])
    assert result["verdict"] == "ALLOW" and result["code"] == 0, result
    assert len(result["calls"]) == 1, result
    call = result["calls"][0]
    assert call["payload"] == payload
    assert call["entry"]["rule"] == "removal-policy" and call["entry"]["kind"] == "let_through_unproven"
    if mode == "primary":
        assert call["entry"]["path"] == "primary"
        assert call["entry"]["reason"] == "UNRESOLVED dynamic_command_head:$PY"
    else:
        assert call["entry"]["path"] == "degraded" and call["entry"]["reason"].startswith("NO_VERDICT ")


@pytest.mark.parametrize("command,refusal", [
    ("ls -la", None),                                            # proven: nothing to record
    ("man rm", None),                                            # proven although it names a removal
    ("$TOOL remove pkg", "removal-policy — UNRESOLVED"),         # unproven and refused: a refusal, not a let-through
    ("rm -rf build", "removal-policy — FORBIDDEN_REMOVAL"),
    # Unproven and let through by the removal policy, then refused by a later rule of the hook: it did not run.
    ("$TOOL --version; git clean -fdx", "git clean"),
])
def test_the_seam_is_not_called_when_nothing_unproven_ran(command, refusal):
    result, _payload, err = decide(command, **PRIMARY_ENV)
    assert result["calls"] == [], result
    if refusal is None:
        assert result["verdict"] == "ALLOW" and result["code"] == 0, (result, err)
    else:
        assert result["code"] == 2 and refusal in err, (result, err)


def test_the_seam_writes_nothing_of_its_own(tmp_path, monkeypatch):
    """This lane builds no log: the hook function does nothing until the record's writer is called from it."""
    monkeypatch.chdir(tmp_path)
    assert R.let_through_unproven({"rule": "removal-policy"}, {"tool_name": "Bash"}) is None
    assert os.listdir(tmp_path) == []
