"""The requirement round (P13-1; D28, D29, D32) as the replays play it: the BA panel or one BA intake, panel QA,
one AskUserQuestion per round file, and what BA analysis maps from the owner's answers.

The questions are product-level (D18). The ask is built as commands/dev.md Step 4b words it, the round file's
questions with id, dimension, assume, spec_ref and each option's ba removed, and its source; this module does
not import the hook's own ask view, so a replay checks the hook against the text, not against itself."""
from __future__ import annotations

import json
import os

from .. import agents

DIMENSIONS = ("intent", "scope", "edge_cases", "acceptance")
ANGLES = ("A", "B", "C")
STRIPPED = ("id", "dimension", "assume", "spec_ref")
# What each panel BA finds and offers; B's root cause differs from A's in the panel-disagree variant.
ROOT_CAUSE = {"A": "the function returns before it applies the rule the request names",
              "B": "the function returns before it applies the rule the request names",
              "C": "the behaviour the owner sees differs from the one the request describes"}
SOLUTION = {"A": ("Fix it where it starts", "Correct the rule where the result is first computed"),
            "B": ("Change only this function", "Touch the one function the request names, nothing around it"),
            "C": ("Match what you see", "Make the visible result match the request, as the owner reads it")}


def question(k: int, dimension: str, text: str, options, assume: str | None = None, spec_ref=None) -> dict:
    labels = [o["label"] for o in options]
    return {"id": f"q{k}", "dimension": dimension, "header": dimension.replace("_", " ").title()[:12],
            "question": text, "multiSelect": False, "options": options, "assume": assume or labels[0],
            "spec_ref": spec_ref}


def _opt(label: str, description: str, ba: str | None = None) -> dict:
    return dict({"label": label, "description": description}, **({"ba": ba} if ba else {}))


def scope_options(panel: dict | None) -> list:
    """The scope question's options: each verified BA's solution, recommended first (A, then B, then C), or two
    plain options without a panel."""
    if not panel:
        return [_opt("Only what was asked", "Deliver the request as written"),
                _opt("A wider tidy-up", "Also tidy what sits next to it")]
    verified = [r["ba"] for r in panel["reports"] if r["root_cause"] == "verified"]
    opts = [_opt(*SOLUTION[b], ba=b) for b in verified]
    return opts if len(opts) >= 2 else opts + [_opt("Only what was asked", "Deliver the request as written")]


def round1(task: str, spec_id: str | None = None, panel: dict | None = None) -> dict:
    """Round 1: four questions, one per dimension (with a spec, the two the spec left open)."""
    qs = [question(1, "intent", "What should change for you when this is done?",
                   [_opt("The result is right", "The answer you get is the correct one"),
                    _opt("It is also faster", "The answer also comes back sooner")]),
          question(2, "scope", "How far should the change reach?", scope_options(panel)),
          question(3, "edge_cases", "What should happen when the input is empty?",
                   [_opt("Return nothing", "An empty input gives an empty result"),
                    _opt("Say it is empty", "An empty input is reported to you")]),
          question(4, "acceptance", "How will you check that it is done?",
                   [_opt("The example passes", "The example in the request gives the expected result"),
                    _opt("I try it myself", "You run it on your own data")])]
    if spec_id:
        qs = [dict(q, id=f"q{k}", spec_ref="Section 5") for k, q in enumerate(qs[2:], 1)]
    doc = {"task_id": task, "round": 1, "spec_id": spec_id, "questions": qs}
    return dict(doc, panel=panel) if panel else doc


def next_round(task: str, n: int, text: str | None = None, spec_id: str | None = None) -> dict:
    """Round n >= 2: one scope question the analysis left open."""
    q = question(1, "scope", text or f"Round {n}: should the change also cover the related report?",
                 [_opt("Yes, cover it", "The related report changes the same way"),
                  _opt("No, leave it", "The related report stays as it is")])
    return {"task_id": task, "round": n, "spec_id": spec_id, "questions": [q]}


def panel(refuted: str = "", unsupported: str = "") -> dict:
    """Panel QA's verdicts on the three root causes (refuted / unsupported: the BAs it marks so)."""
    def verdict(b):
        return "refuted" if b in refuted else "unsupported" if b in unsupported else "verified"
    return {"reports": [{"ba": b, "path": "", "root_cause": verdict(b),
                         "why": f"checked {b}'s cited evidence at the file and line it names"} for b in ANGLES],
            "agreements": ["the requested behaviour is not delivered today"]}


def with_paths(doc: dict, task: str) -> dict:
    for r in (doc.get("panel") or {}).get("reports") or []:
        r["path"] = f"docs/dev/ba-panel-{task}-{r['ba']}.md"
    return doc


def panel_notes(angle: str, root_cause: str | None = None) -> str:
    label, description = SOLUTION[angle]
    other = next(SOLUTION[b] for b in ANGLES if b != angle)
    return (f"## Root cause\n\n{root_cause or ROOT_CAUSE[angle]} (observed: the example in the request gives the "
            "wrong result; inferred: the cited line is where it starts).\n\n"
            f"## Solutions\n\n1. {label}: {description}. Trade-off: the least risk for this angle.\n"
            f"2. {other[0]}: {other[1]}. Trade-off: a different reach.\n\n"
            f"## Recommendation\n\n{label}.\n\n## Points for the owner\n\n- How far the change should reach.\n")


def ask_view(doc: dict) -> list:
    return [{**{k: v for k, v in q.items() if k not in STRIPPED},
             "options": [{k: v for k, v in o.items() if k != "ba"} for o in q["options"]]} for q in doc["questions"]]


def response(tin: dict, mode: str = "answer"):
    """The CLI's tool_response for the owner's way of answering: each question's first (recommended) option, a
    Skip, an AFK auto-continue, or a decline (raised, as the CLI returns an error)."""
    if mode == "decline":
        raise RuntimeError("User declined to answer questions")
    base = {"questions": tin["questions"]}
    if mode == "skip":
        return dict(base, answers={})
    if mode == "afk":
        return dict(base, answers={}, afkTimeoutMs=60000)
    return dict(base, answers={q["question"]: q["options"][0]["label"] for q in tin["questions"]})


def ask(o, rel: str, source: str, label: str, mode: str = "answer", questions=None):
    """Step 4b: the main agent Reads the round file and asks it with ONE AskUserQuestion, its questions verbatim
    (or ``questions``, a paraphrase), metadata.source ``source``. Returns (call, tool_input)."""
    path = os.path.join(o.project, rel)
    o.s.read(path, label=f"{label} Read {rel}", deviation=o.devs.at(f"{label} Read {rel}"))
    doc = json.loads(agents.peek(o.rp, "main", path))
    tin = {"questions": ask_view(doc) if questions is None else questions, "metadata": {"source": source}}
    call = o.s.tool("AskUserQuestion", tin, perform=lambda: response(tin, mode), label=label,
                    deviation=o.devs.at(label))
    return call, tin


def analysis(rp, project: str, task: str, criterion: str) -> dict:
    """BA analysis' mapping (ba.md "Analysis"): every answered question of the task's rounds into
    requirement.contract_refs, every unanswered one into assumptions with its assume label."""
    refs, assumed, n = [], [], 1
    while True:
        rel = next((r for r in (f"docs/dev/requirement-round-{task}-r{n}.json", f"docs/dev/ba-panel-{task}-r1.json")
                    if (n == 1 or "round" in r) and os.path.isfile(os.path.join(project, r))), None)
        if rel is None:
            break
        doc = json.loads(agents.peek(rp, "main", os.path.join(project, rel)))
        ans_path = os.path.join(project, f"docs/dev/requirement-answers-{task}-r{n}.json")
        answers = json.loads(agents.peek(rp, "main", ans_path)).get("answers") or {} if os.path.isfile(ans_path) else {}
        for q in doc["questions"]:
            ref = f"r{n}.{q['id']}"
            if answers.get(q["question"]):
                refs.append({"answer_ref": ref, "criterion_ids": [criterion]})
            else:
                assumed.append({"question_ref": ref, "assume": q["assume"]})
        n += 1
    return {"requirement": {"contract_refs": refs}, "assumptions": assumed}


def chosen(rp, project: str, task: str) -> str | None:
    """The BA whose option the owner chose in the panel round (the chosen option's ba), else None."""
    rel, ans = f"docs/dev/ba-panel-{task}-r1.json", f"docs/dev/requirement-answers-{task}-r1.json"
    if not (os.path.isfile(os.path.join(project, rel)) and os.path.isfile(os.path.join(project, ans))):
        return None
    doc = json.loads(agents.peek(rp, "main", os.path.join(project, rel)))
    answers = json.loads(agents.peek(rp, "main", os.path.join(project, ans))).get("answers") or {}
    for q in doc["questions"]:
        for o in q["options"]:
            if o.get("ba") and answers.get(q["question"]) == o["label"]:
                return o["ba"]
    return None


def fact(rp, key: str, value) -> None:
    """A fact of the replay (close.py's form): out/facts.json beside blocks.json."""
    path = os.path.join(rp.layout.out, "facts.json")
    with rp.acting("driver"):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = []
        doc.append({"key": key, "value": value})
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=1)
