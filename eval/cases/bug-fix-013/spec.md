# Bug-Fix Eval Case 013: Docker volume mount path typo silently mounts empty dir

## Symptom
The `sample-app` container starts cleanly but cannot find any of its
configuration files at runtime: every config lookup returns "not found" and
falls back to defaults. Logs show
`No config files in /etc/sample-app/conf/` despite the host directory
`/srv/sample-app/conf` containing 12 YAML files.

## Reproduction
1. `docker compose up -d sample-app`
2. `docker exec sample-app ls /etc/sample-app/conf` returns nothing.
3. On the host, `ls /srv/sample-app/conf` shows 12 files as expected.

## Suspected Location
`/workspace/sample-app/deploy/docker-compose.yml:34` declares a volume as
`- /srv/sample-app/confs:/etc/sample-app/conf:ro` (note the trailing `s`
on `confs`). Docker silently creates the missing host directory
`/srv/sample-app/confs` (empty) and mounts that, so the container sees an
empty `/etc/sample-app/conf`.

## Expected Behavior
The container sees all 12 YAML files at `/etc/sample-app/conf/` and the app
loads its real configuration. Misconfigured mount paths should fail loudly
rather than silently creating empty directories.

## Acceptance
- Fix the typo: `/srv/sample-app/conf:/etc/sample-app/conf:ro`.
- Add a healthcheck to compose that fails the container if the conf dir is
  empty.
- Add a CI lint step (e.g., `docker-compose config` + a custom script) that
  asserts every host-side bind-mount source already exists in the repo's
  `deploy/` tree.
