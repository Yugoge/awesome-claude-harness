# Harness repair plan

Working material for repairing this harness, phase by phase. Personal values are replaced by placeholders
(`<ACCT_1>`, `<EMAIL_1>`, `<PROJ_1>`, ...); the real values are visible in the code at the cited file:line.

| Path | What it is |
|---|---|
| DECISIONS.md | The owner's decisions. **Overrides PLAN-v1.md** wherever they disagree. Read it first. |
| PLAN-v2.md | The current plan, phases P0-P11 plus P7b (section 14), P1b and P1c (section 15): goal, file:line scope, acceptance tests, risks, technical choices, decision ledger, waves. Line numbers at master 09ab15b. |
| PLAN-v1.md | Earlier plan, phases P0-P9 (old numbering). Loses to PLAN-v2.md wherever they differ. |
| prompts/ | One self-contained prompt per phase, pasted into a new session. |
| landscape/ | Every problem, every file and every file:line, by cluster (00-INDEX.md first). G = stop gates, H = scoring. |
| reports/ | Evidence: runtime verification, armed core-architecture test, adversarial runs, problem list, file manifest. |
| tools/ | The sandbox used for the runtime evidence (below). tools/proto/ holds the planning prototypes of the unified Stop gate (stop_command_gate.py, command_span.py, run_scenarios.py, txbuild.py) and the crash/slow phase stubs PLAN-v2 cites. |
| inventory/ | The d625284 artifact map (P1b planning evidence). |
| audit/ | The 2026-10-23 owner register, artifact ledger, corrections and report-zh. |
| reviews/ | Review records and plan-sync lists. |

## Sandbox (runtime evidence without touching any real ~/.claude)

The harness is executed by replaying real Claude Code hook payloads against a copy of the tree, inside a
private mount namespace where the copy is bound onto `/root/.claude` and `/root`, `/tmp`, `/var/tmp` and
`/dev/shm` are private. A toy product repo with a local bare origin stands in for a user project.

```bash
export SB=$SCRATCH/sb            # any empty scratch directory (not inside the repo)
mkdir -p "$SB"
PYTHONDONTWRITEBYTECODE=1 harness-repair-plan/tools/sb-setup.sh "$PWD"   # copies the working tree, builds venv + toy repos
# replay one event through every hook registered for it in settings.json:
harness-repair-plan/tools/ns.sh bash -c 'cd /root/toyproj && \
  python3 /mnt/sb/tools/runhook.py --settings /root/.claude/settings.json --event PreToolUse --payload /mnt/sb/payloads/p.json --no-snap'
harness-repair-plan/tools/ns.sh bash /mnt/sb/tools/reset.sh      # restore pristine sandbox state between scenarios
harness-repair-plan/tools/ns-alt.sh <cmd>                        # same, but the harness lives at /home/alice/.claude (non-root home)
```

- Inside the namespace the sandbox root is `/mnt/sb`; tools are at `/mnt/sb/tools`, payload files go in `$SB/payloads`.
- `sb-setup.sh` snapshots the working tree (uncommitted changes included), so re-run it after every code change you want to test.
- `runhook.py --help`, `baseline.py` (a full realistic session), `batch.py` (a matrix of ordinary tool calls),
  `one.py` (one event), `single.sh` (one hook) cover the scenarios used in reports/.
- `unshare --mount` needs root in the container. Nested `claude` CLI runs are not used and need the owner's
  explicit permission rule.
