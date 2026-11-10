"""Differential test: build_plan before and after its split into helpers.

tests/differential/build_plan_legacy.py holds ``build_plan`` verbatim as it stood at
commit cc22f78. Every scenario below builds one filesystem and git state, runs the
frozen and the live ``build_plan`` on the same arguments, and asserts the same plan
(every key, value and order) or the same exception (type, message and ``code``).
The scenarios are chosen to reach every branch of the frozen function.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "scripts" / "resolve-commit-repos.py"

_spec = importlib.util.spec_from_file_location("resolve_commit_repos_differential", SCRIPT)
assert _spec and _spec.loader
MODULE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MODULE)

sys.path.insert(0, str(HERE))
import build_plan_legacy  # noqa: E402

LEGACY = build_plan_legacy.bind(MODULE)
TASK = "20261110-000000-diff"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path, *, commit: bool = True) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "Tests")
    if commit:
        (path / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(path, "add", "seed.txt")
        _git(path, "commit", "-q", "-m", "seed")
    return path


def _ledger(paths: list[str]) -> dict[str, list[dict[str, str]]]:
    return {path: [{"old": "o", "new": "n"}] for path in paths}


def _write(control: Path, payload: dict[str, Any], name: str = f"dev-report-{TASK}.json") -> Path:
    path = control / "docs" / "dev" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _dev(modified: list[str], created: list[str] | None = None, **top: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": TASK,
        "request_id": TASK,
        "dev": {"files_modified": modified, "files_created": created or []},
    }
    payload.update(top)
    return payload


class World:
    """One scenario's state: the control repository, the other repositories, the arguments."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.control = _repo(tmp / "control")
        (self.control / "a.txt").write_text("a\n", encoding="utf-8")
        (self.control / "b.txt").write_text("b\n", encoding="utf-8")
        self.kwargs: dict[str, Any] = {
            "task_id": TASK,
            "control_root_arg": str(self.control),
            "supported_repo_args": [],
        }
        self.entangle = False

    def other(self, name: str, *, commit: bool = True) -> Path:
        repo = _repo(self.tmp / name, commit=commit)
        (repo / "x.txt").write_text("x\n", encoding="utf-8")
        return repo

    def report(self, payload: dict[str, Any], **kw: Any) -> Path:
        path = _write(self.control, payload, **kw)
        self.kwargs["report_arg"] = str(path)
        return path


Scenario = Callable[[World], None]
SCENARIOS: dict[str, Scenario] = {}


def scenario(fn: Scenario) -> Scenario:
    SCENARIOS[fn.__name__] = fn
    return fn


# --- report admission -----------------------------------------------------------------

@scenario
def blank_task_id(w: World) -> None:
    w.report(_dev(["a.txt"], owned_edits=_ledger(["a.txt"])))
    w.kwargs["task_id"] = "   "


@scenario
def report_outside_control(w: World) -> None:
    outside = w.tmp / "elsewhere" / f"dev-report-{TASK}.json"
    outside.parent.mkdir(parents=True)
    outside.write_text(json.dumps(_dev(["a.txt"])), encoding="utf-8")
    w.kwargs["report_arg"] = str(outside)


@scenario
def report_found_by_name(w: World) -> None:
    _write(w.control, _dev(["a.txt"], owned_edits=_ledger(["a.txt"])))


@scenario
def no_report_at_all(w: World) -> None:
    pass


@scenario
def report_task_mismatch(w: World) -> None:
    payload = _dev(["a.txt"])
    payload["task_id"] = "other-task"
    w.report(payload)


@scenario
def do_report_section(w: World) -> None:
    payload = {"task_id": TASK, "request_id": TASK, "source": "do",
               "do": {"files_modified": ["a.txt"], "files_created": ["new.txt"]}}
    w.report(payload, name=f"do-report-{TASK}.json")


# --- supported repositories ------------------------------------------------------------

@scenario
def supported_with_duplicates(w: World) -> None:
    other = w.other("other")
    w.kwargs["supported_repo_args"] = [str(w.control), str(other), str(other / "x.txt")]
    w.report(_dev(["a.txt", str(other / "x.txt")],
                  owned_edits=_ledger(["a.txt", str(other / "x.txt")])))


@scenario
def three_repos_sorted(w: World) -> None:
    zed, abc = w.other("zed"), w.other("abc")
    w.kwargs["supported_repo_args"] = [str(zed), str(abc)]
    paths = [str(zed / "x.txt"), "b.txt", str(abc / "x.txt"), "a.txt"]
    w.report(_dev(paths, owned_edits=_ledger(paths)))


@scenario
def supported_repo_not_a_repo(w: World) -> None:
    plain = w.tmp / "plain"
    plain.mkdir()
    w.kwargs["supported_repo_args"] = [str(plain)]
    w.report(_dev(["a.txt"], owned_edits=_ledger(["a.txt"])))


# --- owned path fields -------------------------------------------------------------------

@scenario
def modified_not_a_list(w: World) -> None:
    payload = _dev([])
    payload["dev"]["files_modified"] = "a.txt"
    w.report(payload)


@scenario
def created_holds_a_number(w: World) -> None:
    payload = _dev(["a.txt"])
    payload["dev"]["files_created"] = ["new.txt", 7]
    w.report(payload)


@scenario
def fields_absent(w: World) -> None:
    w.report({"task_id": TASK, "request_id": TASK, "dev": {}})


@scenario
def dual_listed_and_duplicate(w: World) -> None:
    w.report(_dev(["a.txt", "a.txt", "./a.txt"], ["a.txt", "new.txt"],
                  owned_edits=_ledger(["a.txt"])))


@scenario
def owned_path_is_repo_root(w: World) -> None:
    w.report(_dev(["."], owned_edits=_ledger(["."])))


@scenario
def owned_path_empty_string(w: World) -> None:
    w.report(_dev([""]))


@scenario
def created_file_not_on_disk_yet(w: World) -> None:
    w.report(_dev(["relative/new/deep.txt"], ["relative/new/deep.txt"]))


@scenario
def nested_checkout_unadmitted(w: World) -> None:
    nested = _repo(w.control / "nested")
    w.report(_dev([str(nested / "seed.txt")], owned_edits=_ledger([str(nested / "seed.txt")])))


# --- declared unsupported-owner exclusions ------------------------------------------------

@scenario
def unsupported_owner_undeclared(w: World) -> None:
    other = w.other("other")
    w.report(_dev([str(other / "x.txt")]))


@scenario
def unsupported_owner_declared(w: World) -> None:
    foreign, alpha = w.other("foreign"), w.other("alpha")
    paths = [str(foreign / "x.txt"), str(alpha / "x.txt"), str(foreign / "x.txt"), "a.txt"]
    w.kwargs["excluded_unsupported_paths"] = [
        str(foreign / "x.txt"), str(alpha / "x.txt"), str(foreign / "x.txt"),
    ]
    w.report(_dev(paths, [str(foreign / "x.txt")], owned_edits=_ledger(["a.txt"])))


@scenario
def declarations_spelled_two_ways_or_uncanonical(w: World) -> None:
    foreign = w.other("foreign")
    w.kwargs["excluded_unsupported_paths"] = [
        str(foreign / "x.txt"), str(foreign / "." / "x.txt"), "\x00bad", "",
    ]
    w.report(_dev([str(foreign / "x.txt")]))


@scenario
def declared_but_supported(w: World) -> None:
    w.kwargs["excluded_unsupported_paths"] = [str(w.control / "a.txt")]
    w.report(_dev(["a.txt"], owned_edits=_ledger(["a.txt"])))


@scenario
def declared_not_in_owned_set(w: World) -> None:
    foreign = w.other("foreign")
    w.kwargs["excluded_unsupported_paths"] = [
        str(foreign / "x.txt"), str(foreign / "never.txt"), "/no/such/root/file",
    ]
    w.report(_dev([str(foreign / "x.txt")]))


@scenario
def exclusions_none(w: World) -> None:
    w.kwargs["excluded_unsupported_paths"] = None
    w.report(_dev(["a.txt"], owned_edits=_ledger(["a.txt"])))


# --- ownership gate ------------------------------------------------------------------------

@scenario
def gate_backed_by_ledger(w: World) -> None:
    w.entangle = True
    w.report(_dev(["a.txt"], ["new.txt"], owned_edits=_ledger(["a.txt"])))


@scenario
def gate_backed_by_baseline(w: World) -> None:
    w.entangle = True
    w.report(_dev(["a.txt", "b.txt"], owned_edits=_ledger(["a.txt"]),
                  baseline_dirty_snapshot=" M b.txt\nR  old.txt -> a.txt\n"))


@scenario
def gate_unbacked_absent_snapshot(w: World) -> None:
    w.entangle = True
    w.report(_dev(["a.txt", "b.txt"], owned_edits={}))


@scenario
def gate_unbacked_snapshot_not_a_string(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt"], owned_edits=_ledger(["a.txt"]), baseline_dirty_snapshot=["b.txt"]))


@scenario
def gate_unbacked_non_porcelain(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt"], baseline_dirty_snapshot="not porcelain at all"))


@scenario
def gate_unbacked_compliant_empty(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt", "a.txt"], baseline_dirty_snapshot=""))


@scenario
def gate_unbacked_porcelain_present(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt"], baseline_dirty_snapshot=" M a.txt\n"))


@scenario
def gate_unbacked_but_not_entangled(w: World) -> None:
    w.report(_dev(["a.txt", "b.txt"], owned_edits={}))


@scenario
def gate_skipped_when_not_verifying(w: World) -> None:
    w.entangle = True
    w.kwargs["verify_ownership"] = False
    w.report(_dev(["a.txt", "b.txt"], owned_edits={}))


@scenario
def gate_skipped_for_do_report(w: World) -> None:
    w.entangle = True
    payload = {"task_id": TASK, "source": "do", "do": {"files_modified": ["a.txt"]}}
    w.report(payload, name=f"do-report-{TASK}.json")


@scenario
def landed_whole_exempts(w: World) -> None:
    w.entangle = True
    w.report(_dev(["a.txt", "b.txt"], owned_edits=_ledger(["a.txt"]), pre_edit_snapshots={},
                  baseline_dirty_snapshot="",
                  files_landed_whole=[{"path": "b.txt", "diff_sha256": "0", "reason": "r"},
                                      "junk", {"path": 3}]))


@scenario
def landed_whole_dual_listed(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt"], owned_edits={}, pre_edit_snapshots=_ledger(["b.txt"]),
                  baseline_dirty_snapshot="",
                  files_landed_whole=[{"path": "b.txt"}]))


@scenario
def landed_whole_without_claim_fields(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt"], baseline_dirty_snapshot="", files_landed_whole=[{"path": "b.txt"}]))


@scenario
def landed_whole_owned_edits_malformed(w: World) -> None:
    w.report(_dev(["b.txt"], owned_edits=["b.txt"], files_landed_whole=[{"path": "b.txt"}]))


@scenario
def landed_whole_pre_edit_snapshots_null(w: World) -> None:
    w.report(_dev(["b.txt"], owned_edits={}, pre_edit_snapshots=None,
                  files_landed_whole=[{"path": "b.txt"}]))


@scenario
def landed_whole_uncanonical_ledger_key(w: World) -> None:
    w.report(_dev(["b.txt"], owned_edits={"": [{"old": "o", "new": "n"}]},
                  files_landed_whole=[{"path": "b.txt"}]))


@scenario
def landed_whole_empty_list(w: World) -> None:
    w.entangle = True
    w.report(_dev(["b.txt"], owned_edits=["malformed"], baseline_dirty_snapshot="",
                  files_landed_whole=[]))


# --- repository targets -----------------------------------------------------------------------

@scenario
def detached_head(w: World) -> None:
    other = w.other("other")
    _git(other, "checkout", "-q", "--detach")
    w.kwargs["supported_repo_args"] = [str(other)]
    w.report(_dev([str(other / "x.txt")], owned_edits=_ledger([str(other / "x.txt")])))


@scenario
def repository_without_commits(w: World) -> None:
    empty = w.other("empty", commit=False)
    w.kwargs["supported_repo_args"] = [str(empty)]
    w.report(_dev([str(empty / "x.txt")], owned_edits=_ledger([str(empty / "x.txt")])))


def _outcome(fn, kwargs: dict[str, Any]) -> tuple[str, Any]:
    try:
        plan = fn(**kwargs)
    except Exception as exc:  # the comparison is over every exception, not only PlanError
        return "raised", (type(exc).__qualname__, str(exc), getattr(exc, "code", None))
    return "returned", json.dumps(plan)  # no sort_keys: key order is compared too


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_legacy_and_refactored_build_plan_agree(name: str, tmp_path: Path, monkeypatch) -> None:
    world = World(tmp_path)
    SCENARIOS[name](world)
    if world.entangle:
        # The journal finds nothing in a fresh repository; stand in for an ENTANGLED verdict so
        # the gate's refusal paths are reached. Both versions read the same module global.
        monkeypatch.setattr(MODULE, "_ledger_entangled", lambda identities: list(identities))
    legacy = _outcome(LEGACY, world.kwargs)
    refactored = _outcome(MODULE.build_plan, world.kwargs)
    assert refactored == legacy


def test_the_frozen_copy_is_the_pre_split_function() -> None:
    """The reference keeps the old body: one function, all its branches inline."""
    import ast

    tree = ast.parse(Path(build_plan_legacy.__file__).read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert names == ["build_plan", "bind"]
    assert LEGACY.__kwdefaults__ == MODULE.build_plan.__kwdefaults__
