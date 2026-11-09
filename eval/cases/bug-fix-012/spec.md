# Bug-Fix Eval Case 012: systemd unit missing RestartSec causes restart storm

## Symptom
When the `sample-worker.service` crashes, systemd attempts to restart it
immediately and burns through the `StartLimitBurst=5` allowance in well
under a second, after which the service is permanently disabled until manual
`systemctl reset-failed`. Operators have to intervene 2-3 times per week.

## Reproduction
1. `sudo systemctl start sample-worker.service`
2. From a second shell, `pkill -9 sample-worker` repeatedly.
3. After ~5 quick crashes (well under 1s total), `systemctl status` shows
   `Active: failed (Result: start-limit-hit)` and the unit will not restart.

## Suspected Location
`/workspace/sample-app/deploy/systemd/sample-worker.service` declares
`Restart=on-failure` and `StartLimitBurst=5` but omits both `RestartSec=`
and `StartLimitIntervalSec=`. Defaults are 100ms restart with no burst
window expansion, so any rapid crash burns the burst allowance instantly.

## Expected Behavior
After a crash, systemd waits at least 5 seconds before restarting. The burst
window is wide enough (e.g. `StartLimitIntervalSec=300`) that 5 crashes in 5
minutes is the realistic limit, not 5 crashes in 500ms.

## Acceptance
- Add `RestartSec=5` and `StartLimitIntervalSec=300` to the unit file.
- Add a comment explaining the rationale referencing the operator runbook.
- A scripted test (`tests/test_unit_file.sh`) parses the unit file and
  asserts both keys are present with sensible values.
