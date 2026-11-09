# Bug-Fix Eval Case 015: Log rotation aborts because old file still locked

## Symptom
`logrotate` runs nightly via cron and fails on `sample-app.log` with
`error: error renaming /var/log/sample-app.log: Device or resource busy`.
The log file grows unbounded until disk-space alerts fire 3-4 days later
and an operator manually truncates the file.

## Reproduction
1. Wait for the nightly cron at 03:25.
2. `journalctl -u logrotate.service` shows the error above.
3. `lsof /var/log/sample-app.log` shows the running app process holds an
   open file descriptor on the file.

## Suspected Location
`/workspace/sample-app/deploy/logrotate.d/sample-app` declares
`rotate 14, daily, missingok, compress` but no `copytruncate` and no
`postrotate ... endscript` to send `SIGHUP` to the app. The app caches its
log fd and never reopens, so the rename fails on running file descriptors.

## Expected Behavior
Nightly rotation succeeds. The app continues writing to the freshly created
`sample-app.log` rather than the rotated `sample-app.log.1` after rotation.
Disk usage stays bounded by `rotate 14`.

## Acceptance
- Add `copytruncate` to the logrotate config OR add a `postrotate` block
  that runs `systemctl reload sample-app.service` (preferred, as
  copytruncate can drop in-flight writes).
- A scripted test forces a rotation in a sandbox and asserts
  (a) the rotated file exists, (b) the live file has been truncated to 0,
  (c) a subsequent log line lands in the live file, not the rotated one.
- Document the chosen strategy in the file header.
