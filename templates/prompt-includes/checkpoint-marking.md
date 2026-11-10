# Checkpoint Marking Contract

Read this file when your dispatch passes a non-empty `<SPEC_ID>` and names your cp-state file,
`.claude/specs/<SPEC_ID>/cp-state-<role>.json` (or a numbered same-role slot): a `/spec`-driven checklist
binds you to mark every atomic checkpoint listed in it. Without a `<SPEC_ID>` (for example `/dev` without
`--spec`) no cp-state file exists for you and nothing below applies.

**File you own**: `.claude/specs/<SPEC_ID>/cp-state-<role>.json`, `<role>` being your own agent name.

**cp-state lifecycle.** Every cp-state mutation goes through
`python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py"` (activate `${CLAUDE_HOME:-$HOME/.claude}/venv`
first):

| Subcommand | Purpose |
|---|---|
| `mark --spec-id <S> --agent <role> --agent-id <ID> --cp-id cp-NN` | Mark checkpoint done |
| `waive --spec-id <S> --agent <role> --agent-id <ID> --cp-id cp-NN` | Waive cp (auto-records actor + ISO timestamp) |
| `check-out --spec-id <S> --agent <role> --agent-id <ID>` | Finalize, set `is_running:false` (auto-fires once all cps terminal) |
| `check-in --spec-id <S> --agent <role> --agent-id <ID>` | Re-open your own closed slot |
| `status --spec-id <S> [--agent <role>]` | Read-only inspection |

**PROHIBITED**: do NOT direct-`Edit` / `Write` / `MultiEdit` / `NotebookEdit` / Bash-write a cp-state JSON
file (`.claude/specs/<SPEC_ID>/cp-state-*.json`). The `pretool-cp-state-write-guard.py` hook denies these;
only `spec-check.py` may write. Why: spec-check.py provides auto-checkout, audit fields (`marked_at`,
`marked_by`), fcntl serialization across concurrent agents, and role-scope enforcement. Bypassing it
corrupts the audit trail.

**On entry**: Read your cp-state file before doing substantive work. That read registers you
(`pretool-cp-checkin.py`): the file you read becomes your slot, its `is_running` true and its `agent_id`
your own agent id. Use that `agent_id` value as `--agent-id` (no shell variable supplies it).

**During work**: treat each `checkpoints[].id` entry as a required checklist item. Immediately after you
complete a checkpoint's atomic action, mark it done (`mark`, with `--spec-id <SPEC_ID>`, `--agent <role>`,
`--agent-id <that agent_id>` and `--cp-id cp-NN`). If a checkpoint legitimately does not apply to this
run, waive it with the same arguments.

**On exit**: every checkpoint of your slot must be in state `done` or `waived`. `subagentstop-cp-enforce.py`
runs when you stop and, as shipped (settings.json sets `CP_ENFORCE_MODE=block`), blocks your stop (exit 2)
while a checkpoint of your own slot is still `pending`; its message lists those cp-IDs. Mark or waive them,
then stop again. Slots other agents hold never block your stop.

**Cross-role scope (unconditional).** You may mark or waive only your own role's checkpoints: `spec-check.py`
refuses `--agent <X>` for any other role (exit 1, stderr explains the role mismatch), with no override flag,
sentinel or orchestrator escape, main-agent invocations included. A checkpoint of another role is that
role's to mark; if one blocks your work, name its cp-id and owning role in your report.

Rule: cp-state keeps per-agent atomic-action coverage auditable; unmarked or cross-role-marked checkpoints
hollow out that audit trail.
