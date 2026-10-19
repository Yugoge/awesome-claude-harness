# Root conftest — `generated` marker gate for tests/generated/.
#
# Phase 3 of docs/reference/test-suite-overhaul-plan.md (ratified decision in
# docs/reference/generated-tests-policy.md): retire the blanket
# `--ignore=tests/generated` and instead make the test-writer AC skeletons
# OPT-IN-RUNNABLE behind a `generated` pytest marker, with the generated tree not
# collected by the DEFAULT run.
#
# Mechanism (standard pytest, no hacks):
#   * pytest_ignore_collect  — the default run never DESCENDS into tests/generated,
#     so a parent-dir arg (`tests`) or bare `pytest` cannot pull it in (and cannot
#     be reddened by an import-time bit-rot error). It is collected only when the
#     invocation explicitly targets a path at/under tests/generated, or passes
#     --run-generated.
#   * pytest_itemcollected  — auto-applies `pytest.mark.generated` to every test
#     collected under tests/generated/ (applied at collection time so a `-m
#     generated` selection can see the marker before the built-in deselection runs).
#   * pytest_collection_modifyitems — deselects generated-marked items UNLESS the
#     run explicitly opts in (`-m generated` or --run-generated).
#   * pytest_make_collect_report — when a file UNDER tests/generated raises at
#     COLLECTION/IMPORT time (bit-rot: missing import, renamed symbol, duplicate-
#     basename collision, syntax error), the wrapper rewrites the failed collect
#     report into a clean SKIP (reason "generated skeleton bit-rotted: <error>")
#     instead of a hard ERROR — so the opt-in run distinguishes an expected
#     bit-rotted skeleton from a real regression. Scoped to tests/generated ONLY;
#     a collection error anywhere else stays a real ERROR (never masks a real
#     test-tree import failure). The runtime xfail hook below cannot catch these
#     because they fail before any test runs.
#   * pytest_runtest_makereport — reports a `TEST_INCOMPLETE:` pytest.fail as an
#     xfail so `-m generated` distinguishes "incomplete skeleton" (x) from a real
#     regression / bit-rot (F).
#
# All hooks are no-ops for anything outside tests/generated/, so hooks/tests and
# the non-generated part of tests/ are completely unaffected.

import os
import pathlib
import sys
import tempfile

import pytest

_GENERATED_DIR = (pathlib.Path(__file__).parent / "tests" / "generated").resolve()

# Hermetic environment. Set at import, before any test module is collected,
# because several modules bind state paths when first imported (for example
# hooks/lib/allowlist.py SENTINEL_GRANT_DIR). One session-wide state root, so
# the in-process view and every hook a test spawns resolve the same grants and
# consent flags, and none of them is the shared default /tmp namespace a live
# session uses. HOME and CLAUDE_CONFIG_DIR start at a scratch home so nothing
# reads or writes the real one; the per-test fixture below moves them again.
_HERMETIC_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="harness-tests-"))
for _name in ("state", "home"):
    (_HERMETIC_ROOT / _name).mkdir()
os.environ["CLAUDE_STATE_DIR"] = str(_HERMETIC_ROOT / "state")
os.environ["HOME"] = str(_HERMETIC_ROOT / "home")
os.environ["CLAUDE_CONFIG_DIR"] = str(_HERMETIC_ROOT / "home" / ".claude")
os.environ["CLAUDE_PYTHON_BIN"] = sys.executable
# The empty-lists document init writes (scripts/bootstrap), tracked so a run
# never depends on the runner's own protected-runtime file.
os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = str(
    pathlib.Path(__file__).parent / "hooks" / "tests" / "fixtures" / "protected-runtime.json"
)


@pytest.fixture(autouse=True)
def _hermetic_env(tmp_path_factory):
    """Give each test its own empty HOME and restore the environment afterwards,
    so a test that assigns os.environ directly cannot leak into later tests."""
    saved = dict(os.environ)
    home = tmp_path_factory.mktemp("home")
    os.environ["HOME"] = str(home)
    os.environ["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    yield
    os.environ.clear()
    os.environ.update(saved)


def pytest_addoption(parser):
    parser.addoption(
        "--run-generated",
        action="store_true",
        default=False,
        help="Opt in to collecting/running the test-writer AC skeletons under "
             "tests/generated/ (see docs/reference/generated-tests-policy.md).",
    )


def _is_under_generated(path) -> bool:
    if path is None:
        return False
    try:
        p = pathlib.Path(str(path)).resolve()
    except (OSError, ValueError):
        return False
    return p == _GENERATED_DIR or _GENERATED_DIR in p.parents


def _generated_explicitly_targeted(config) -> bool:
    """True when the invocation opts the generated tree into COLLECTION: either
    --run-generated, or a command-line path argument at/under tests/generated.
    (Deliberately NOT triggered by `-m generated` alone — that keeps
    `pytest hooks/tests tests -m generated` from ever descending into the tree.)"""
    if config.getoption("--run-generated", default=False):
        return True
    for arg in config.invocation_params.args:
        if arg.startswith("-"):
            continue
        candidate = arg.split("::", 1)[0]
        if _is_under_generated(candidate) or _is_under_generated(config.rootpath / candidate):
            return True
    return False


def _generated_opted_in(config) -> bool:
    """True when the run explicitly ELECTS to execute generated items:
    --run-generated, `-m` expression referencing the `generated` marker, or an
    explicit path at/under tests/generated. An explicit test target is already
    an intentional opt-in and must not produce pytest exit 5 via deselection."""
    if config.getoption("--run-generated", default=False):
        return True
    if _generated_explicitly_targeted(config):
        return True
    markexpr = config.getoption("markexpr", default="") or ""
    return "generated" in markexpr


def pytest_ignore_collect(collection_path, config):
    if _is_under_generated(collection_path) and not _generated_explicitly_targeted(config):
        return True
    return None


def pytest_itemcollected(item):
    if _is_under_generated(item.path):
        item.add_marker(pytest.mark.generated)


def pytest_collection_modifyitems(config, items):
    generated = [it for it in items if _is_under_generated(it.path)]
    if not generated or _generated_opted_in(config):
        return
    remaining = [it for it in items if it not in generated]
    config.hook.pytest_deselected(items=generated)
    items[:] = remaining


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    # SCOPED to tests/generated ONLY: a file that raises at COLLECTION/IMPORT time
    # (bit-rot — missing import, renamed symbol, duplicate-basename collision,
    # syntax error) becomes a clean SKIP-with-reason instead of a hard collection
    # ERROR, so the opt-in `-m generated` run distinguishes an expected bit-rotted
    # skeleton from a real regression. These fail before any test runs, so the
    # runtime TEST_INCOMPLETE->xfail hook cannot catch them. A collection error
    # ANYWHERE ELSE is left untouched and still surfaces as a real ERROR — this
    # never masks a genuine test-tree import failure.
    rep = yield
    if rep.failed and _is_under_generated(getattr(collector, "path", None)):
        call = getattr(rep, "call", None)
        excinfo = getattr(call, "excinfo", None) if call is not None else None
        if excinfo is not None:
            detail = f"{excinfo.type.__name__}: {excinfo.value}"
        else:
            detail = str(rep.longrepr)
        detail = (detail.strip().splitlines() or ["collection error"])[0]
        path = getattr(collector, "path", None)
        rep.outcome = "skipped"
        rep.longrepr = (
            str(path) if path is not None else collector.nodeid,
            None,
            f"generated skeleton bit-rotted: {detail}",
        )
    return rep


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if _is_under_generated(item.path) and rep.when == "call" and rep.failed \
            and call.excinfo is not None and "TEST_INCOMPLETE" in str(call.excinfo.value):
        rep.outcome = "skipped"
        rep.wasxfail = "TEST_INCOMPLETE skeleton (unrealized test-writer stub)"
    return rep
