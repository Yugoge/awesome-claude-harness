"""The Stop gate's chain module skips the informational (full) completeness run unless the canonical's
blocking_issues holds an entry of a completeness diagnostic's form -- the only way that run can decide
(COMPLETENESS_CHANNEL_VIOLATION). Pinned here: (1) every diagnostic the check builds has that form, so the
condition is necessary; (2) the Stop path calls the full run only then, and decides as before."""
import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INV = _load(ROOT / "tests" / "test_completeness_channel_invariant.py", "_on_demand_invariant")
AGG_SRC = (ROOT / "scripts" / "aggregate-dev-report.py").read_text(encoding="utf-8")


def _function(name):
    return next(n for n in ast.walk(ast.parse(AGG_SRC)) if isinstance(n, ast.FunctionDef) and n.name == name)


def _rel_first(node) -> bool:
    """f"{rel}: ...", "%s: ..." % (rel, ...), or _span_shortfall_diagnostic(rel, ...)."""
    if isinstance(node, ast.JoinedStr):
        head, *rest = node.values
        return (isinstance(head, ast.FormattedValue) and isinstance(head.value, ast.Name) and head.value.id == "rel"
                and rest and isinstance(rest[0], ast.Constant) and rest[0].value.startswith(": "))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return (isinstance(node.left, ast.Constant) and node.left.value.startswith("%s: ")
                and isinstance(node.right, ast.Tuple) and isinstance(node.right.elts[0], ast.Name)
                and node.right.elts[0].id == "rel")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_span_shortfall_diagnostic":
        return isinstance(node.args[0], ast.Name) and node.args[0].id == "rel"
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):  # last_diagnostic or f"{rel}: ..."
        return all(_rel_first(v) or (isinstance(v, ast.Name) and v.id == "last_diagnostic") for v in node.values)
    return False


def test_every_diagnostic_the_check_builds_has_the_form_the_predicate_reads():
    """Complete by construction: _apply_completeness_check appends only the diagnostic string returned by
    _completeness_check_file; that function's failing results are its `return False, X` statements, X being
    a literal form or `last_diagnostic`, whose every assignment is walked; _span_shortfall_diagnostic's
    returns are walked too. Each must start with the owned path followed by ": "."""
    apply = _function("_apply_completeness_check")
    appends = [n for n in ast.walk(apply) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append"]
    assert [ast.unparse(n) for n in appends] == ["diagnostics.append(diagnostic)"]
    sources = [n for n in ast.walk(apply) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Tuple) and ast.unparse(t.elts[1]) == "diagnostic" for t in n.targets)]
    assert [ast.unparse(n.value.func) for n in sources] == ["_completeness_check_file"]
    check = _function("_completeness_check_file")
    failing = [n.value.elts[1] for n in ast.walk(check) if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)
               and isinstance(n.value.elts[0], ast.Constant) and n.value.elts[0].value is False]
    assigned = [n.value for n in ast.walk(check) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "last_diagnostic" for t in n.targets)]
    assigned = [v for v in assigned if not (isinstance(v, ast.Constant) and v.value == "")]  # the initial ""
    shortfall = [n.value for n in ast.walk(_function("_span_shortfall_diagnostic")) if isinstance(n, ast.Return)]
    assert len(failing) >= 5 and len(assigned) >= 6 and len(shortfall) == 2
    bad = [ast.unparse(v)[:120] for v in failing + assigned if not (_rel_first(v) or (
        isinstance(v, ast.Name) and v.id == "last_diagnostic"))]
    bad += [ast.unparse(v)[:120] for v in shortfall
            if not (isinstance(v, ast.BinOp) and isinstance(v.left, ast.Constant) and v.left.value.startswith("%s: ")
                    and ast.unparse(v.right.elts[0]) == "rel")]
    assert not bad, bad


def _stop_resolver(monkeypatch, on_demand=True):
    resolver = _load(ROOT / "scripts" / "resolve-dev-artifact-chain.py", "_on_demand_resolver")
    resolver.FULL_COMPLETENESS_ON_DEMAND = on_demand
    aggregate, calls = resolver._load_aggregate_module(), []
    real = aggregate._apply_completeness_check

    def counted(*args, **kwargs):
        calls.append(kwargs.get("same_cycle_only", False))
        return real(*args, **kwargs)
    aggregate._apply_completeness_check = counted
    monkeypatch.setattr(resolver, "_load_aggregate_module", lambda: aggregate)
    return resolver, aggregate, calls


def _scenario(tmp_path, monkeypatch, extra_blockers=None):
    root = tmp_path / "proj"
    INV.build_scenario(root, foreign=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    INV.AGG._FOREIGN_CLAIM_INDEX_CACHE.clear()
    INV.AGG.main(["--task-id", INV._TASK_ID])
    path = root / "docs" / "dev" / f"dev-report-{INV._TASK_ID}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if extra_blockers is not None:
        doc["blocking_issues"] = list(doc.get("blocking_issues") or []) + extra_blockers(doc)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return root, doc


def _codes(result):
    return sorted((e["code"], e["path"], e["detail"]) for e in result["errors"])


def test_stop_path_without_a_diagnostic_shaped_blocker_skips_the_full_run(tmp_path, monkeypatch):
    root, doc = _scenario(tmp_path, monkeypatch)
    assert doc[INV.AGG.COMPLETENESS_GAPS_KEY], "precondition: the full run has findings to skip"
    stop, _agg, calls = _stop_resolver(monkeypatch)
    lazy = stop.resolve_chain(root, INV._TASK_ID)
    assert calls == [True] and "ownership_completeness_informational" not in lazy
    eager, _agg, both = _stop_resolver(monkeypatch, on_demand=False)
    full = eager.resolve_chain(root, INV._TASK_ID)
    assert both == [False, True] and full["ownership_completeness_informational"]
    assert _codes(lazy) == _codes(full)


def test_stop_path_with_a_blocker_equal_to_a_diagnostic_raises_the_violation_as_before(tmp_path, monkeypatch):
    root, _doc = _scenario(tmp_path, monkeypatch, lambda d: list(d[INV.AGG.COMPLETENESS_GAPS_KEY]))
    stop, _agg, calls = _stop_resolver(monkeypatch)
    lazy = stop.resolve_chain(root, INV._TASK_ID)
    eager, _agg, _both = _stop_resolver(monkeypatch, on_demand=False)
    assert calls == [False, True] and INV.CHANNEL_CODE in [e["code"] for e in lazy["errors"]]
    assert _codes(lazy) == _codes(eager.resolve_chain(root, INV._TASK_ID))


def test_stop_path_with_a_blocker_of_another_form_skips_and_raises_nothing(tmp_path, monkeypatch):
    root, _doc = _scenario(tmp_path, monkeypatch, lambda d: ["a reviewer's note: not a diagnostic"])
    stop, _agg, calls = _stop_resolver(monkeypatch)
    lazy = stop.resolve_chain(root, INV._TASK_ID)
    assert calls == [True] and INV.CHANNEL_CODE not in [e["code"] for e in lazy["errors"]]
    eager, _agg, _both = _stop_resolver(monkeypatch, on_demand=False)
    assert _codes(lazy) == _codes(eager.resolve_chain(root, INV._TASK_ID))


def test_the_stop_gate_asks_its_chain_module_for_the_on_demand_run():
    gate = (ROOT / "hooks" / "stop-command-gate.py").read_text(encoding="utf-8")
    assert "chain.FULL_COMPLETENESS_ON_DEMAND = True" in gate
