# Bug-Fix Eval Case 014: Env var precedence reversed — .env overrides shell

## Symptom
Operators set `DATABASE_URL` in the shell to point at a maintenance replica,
but the running process always connects to the primary URL listed in the
repo's `.env` file. Setting the var in the shell, in `/etc/environment`, or
in the systemd `Environment=` directive all have no effect.

## Reproduction
1. `export DATABASE_URL=postgresql://replica.example.com/sample`
2. `python -c "import os; os.environ['DATABASE_URL']" ` — confirms the env
   value is the replica URL.
3. Start the app: it logs `Connecting to postgresql://primary.example.com/sample`
   (the value from `.env`).

## Suspected Location
`/workspace/sample-app/src/config/loader.py:21` calls
`dotenv.load_dotenv('.env', override=True)` at import time. The
`override=True` flag causes any value in `.env` to overwrite the existing
shell environment, which is the opposite of expected precedence.

## Expected Behavior
Shell env vars take precedence over `.env`. `.env` provides defaults only
for vars not already set. Operators can override any value at process
start without editing repo files.

## Acceptance
- Change to `dotenv.load_dotenv('.env', override=False)`.
- Add a unit test that sets an env var, calls the loader, and asserts the
  shell value wins over the `.env` value.
- Update the README's "Configuration" section to document precedence
  clearly: shell > systemd Environment= > .env > built-in defaults.
