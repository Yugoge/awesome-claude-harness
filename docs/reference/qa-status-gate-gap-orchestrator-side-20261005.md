# The QA-verdict gate does not cover the orchestrator — still open 2026-10-05

The operator's recurring complaint, in their own words (2026-10-01T10:19:15Z):

> 为什么我的系统这么久了还会出现QA拒绝但是dev还是被orchestrator声称完成的情况？？？？？

and earlier the same day, the requirement it refers back to:

> 还是没懂你的意思，和我最初的强制出现fail就必须改进到彻底pass才能算dev完成有任何关系？

That session was explicitly narrowed by the operator to *answer the question only*
("我只管你是否回答了我的问题"), so no fix was attempted and none should have been.
The answer it produced is recorded here because the gap is **still present** four days
later, and because the analysis existed only inside a workspace queued for deletion.

## The gap, with coordinates

`hooks/stop-completion-gate.py` is a registered `Stop` hook and it **does** call the
resolver in-process (`:419-420`). But its trigger predicate
`_is_sole_missing_completion` (`:229-250`) fires only when the resolver returns
`status=="fail"` with **exactly one** error whose `code=="MISSING_ARTIFACT"` and whose
path is the completion artifact.

When QA has ruled `fail`, the resolver returns `INVALID_QA_STATUS`
(`scripts/resolve-dev-artifact-chain.py:297`, message `qa.status is {actual!r};
expected 'pass'`). That code does not match the predicate, so the predicate returns
False, `findings` is empty, and `:445` (`if not findings: … return {"status": "pass"}`)
**lets the session end.**

So the gate that exists enforces *"the completion file must exist"*. It does not
enforce *"QA must have passed"*. Those are different propositions and only the first
one has a gate.

Across the four registered `Stop` hooks — `stop-workflow-coordinator.py`,
`stop-do-report-gate.py`, `stop-obligation-gate.py`, `stop-completion-gate.py` — the
pattern `qa\.status|INVALID_QA_STATUS|qa_status|qa-report` matches **zero** times.
Positive control for that measurement: the same pattern by the same method matches four
other files under `hooks/` (`prompt-workflow.py`, `subagentstop-e2e-enforce.py`,
`pretool-gitignore-preflight.py`, `subagentstop-artifact-contract-enforce.py`), so the
zero is a real zero and not a broken search.

## Why the gates that do read the verdict don't help here

Both automatic readers of `qa.status` live on the **SubagentStop** side:

- `hooks/subagentstop-artifact-contract-enforce.py:498-533` (`_wire_qa_chain`, landed
  by `f1276a90e`) — a real gate, but it blocks only when the stopping subagent's own
  declared artifact path is involved (`:525 if norm in qa_owned`). A verdict sitting on
  someone else's path becomes an advisory `upstream_defect_notice` and does not block.
- the same file's `required_values` check (`:881-893`) via
  `hooks/lib/obligation.py:339 evaluate_required_values`, against the declaration in
  `commands/dev.md:1023` (`required_values: {"qa.status": ["pass"]}`).

**The orchestrator is the main session. SubagentStop does not cover it.** So the exact
path the operator named — orchestrator declares dev complete while QA has ruled fail —
passes through with nothing raising an error anywhere.

## The second opening: the declaration is self-served

`required_values` is written into each dispatch by the orchestrator itself
(`commands/dev.md:1023`, "Orchestrator instantiates per-dispatch"). The hook that is
supposed to require an `<obligation>` block in every dispatch,
`hooks/pretool-obligation-gate.py:155`, defaults to **advisory**:

```python
mode = os.environ.get(SWITCH_ENV, "advisory").strip().lower()
```

and `CLAUDE_OBLIGATION_GATE` does not appear among `settings.json`'s env keys. A missing
block is logged and `exit 0`. So an orchestrator that omits or rewrites
`required_values` is refused by nothing.

This is the `declared-vs-actual-with-nothing-binding-them` shape again: the rule exists
in three places, and for two of them the question *"who compares it at runtime?"* has no
answer.

| Where the rule is written | Runtime comparator |
|---|---|
| per-account `memory/*.md` notes | **none** — memory is injected as context; no process reads or compares it |
| `commands/dev.md:1386` (run the resolver), `:1079-1099` (qa.status branches) | **none** — prose addressed to the orchestrator; whether it runs is decided by the party being constrained |
| `commands/dev.md:1023` `required_values` | **yes, with an opening** — `obligation.py:339` ← `subagentstop-artifact-contract-enforce.py:885`, fires only on a QA subagent's SubagentStop, and its own precondition gate is advisory |

## What would close it

Named by the reading cycle, not attempted:

1. Widen `stop-completion-gate.py:229-250` so `INVALID_QA_STATUS` is a blocking finding
   alongside `MISSING_ARTIFACT` — i.e. put the verdict check on the **orchestrator's own
   Stop path**, which is the only side that can refuse the completion claim.
2. Set `CLAUDE_OBLIGATION_GATE=block` in `settings.json` env so `qa.status: ["pass"]`
   cannot be silently omitted from a dispatch.

Item 1 is the load-bearing one and is currently absent from all four registered `Stop`
hooks.

## Measurement provenance

The coordinates above were produced by a read-only cycle and are reported with its
method and positive controls. What was independently re-measured while writing this
file: `settings.json` at HEAD registers eight `SubagentStop` hooks across five match
blocks, including `subagentstop-artifact-contract-enforce.py` at `settings.json:899`;
`8934049b9` and `f1276a90e` are commit objects and ancestors of HEAD. The
`stop-completion-gate.py` and `pretool-obligation-gate.py` line-level readings are the
reading cycle's, with the zero-match measurement carrying the positive control quoted
above; they have not been re-run independently. Anyone acting on item 1 should re-read
`:229-250` and `:445` first rather than trusting this file.

## A separate finding from the same reading pass

Task `20261003-170215` fixed two harness defects. One half landed in `1fdbd3767`
(carrying `Task-id: 20261003-170215`). The other half —
`hooks/pretool-do-block-subagents.py`, 129 → 177 lines — landed in `2d78e4c12`, an
`auto-bulk: end-of-cycle commit` **carrying no task-id at all**. So `git log --grep` on
the task-id finds one commit and reports the task as singly-landed, while the fix
actually spans two commits, one of which is attributed to nothing. This is the
`producer-consumer-landing-asymmetry` shape: the commit that names the task is honest
about itself and misleading about the task.
