"""A container command with an option the removal rule's table does not know is read, not refused.

Four container runs were refused on one day as an unresolved removal (`unknown_option:--dns`, `--memory-swap`)
although nothing in them removes a file: `--rm` made the text look like a removal and the option table did not
know the option, so the rule could not tell where the image and the container's command begin. Docker's option
reader knows two kinds of option, a flag and an option taking one value; an option the table does not know is
read both ways and the container's command is judged under every reading, so a removal inside it stays judged
wherever it can stand. The commands below are data; none is executed.
"""
import io
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

import bash_execution_boundary as eb  # noqa: E402

_argv, sys.argv = sys.argv, [sys.argv[0], HOOKS_DIR]
try:
    import bash_safety_rules as R  # noqa: E402
finally:
    sys.argv = _argv
R.HOOKS, R.LIB = HOOKS_DIR, os.path.join(HOOKS_DIR, "lib")


def refused(command):
    """removal_policy() alone, in this process: (refused, stderr text)."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    saved, real = os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT"), sys.stderr
    os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = "120s"
    sys.stderr = err = io.StringIO()
    try:
        R.removal_policy(payload, command)
        return False, ""
    except SystemExit as exc:
        assert exc.code == 2, exc.code
        return True, err.getvalue()
    finally:
        sys.stderr = real
        os.environ.pop("CLAUDE_HOOK_BOUNDARY_TIMEOUT", None)
        if saved is not None:
            os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = saved


# The four recorded refusals, with neutral names and paths in place of the recorded ones.
RECORDED = {
    "a DNS server": (
        "cd /srv/rel; docker run --rm --dns 127.0.0.1 --network app_default --entrypoint python app-api:t1 -c \"\n"
        "import socket\nfor h in ('db','example.com'):\n    try: print(h, socket.gethostbyname(h))\n"
        "    except Exception as e: print(h,'FAIL',type(e).__name__)\n\" 2>&1 | tail -5; "
        "tail -3 evidence/build.log 2>/dev/null"),
    "a swap limit before a mount": (
        "S=/srv/scratch/qa\ncd /srv/rel/work/int\n"
        "docker run --rm --name qa-int --network qa-net --memory 700m --memory-swap 700m "
        "-e PYTHONDONTWRITEBYTECODE=1 -e TEST_DATABASE_URL=postgresql://u:p@qa-pg:5432/qa "
        "-v /srv/rel/work/int:/repo:ro -w /repo/backend app-api:t2 python -m pytest tests/test_a.py "
        "-p no:cacheprovider -q -x 2>&1 | tail -80 > $S/int-run1"),
    "a swap limit before environment values": (
        "cd /srv/work/lane && docker run --rm --network fix-net --memory 768m --memory-swap 768m "
        "-e ADMIN_DSN=postgresql://u:p@fix-pg:5432/postgres -e PYTHONPATH=/work/backend "
        "-v /srv/work/lane:/work -w /work app-api:t3 python -m pytest backend/tests/test_b.py -q -x "
        "-p no:cacheprovider 2>&1 | tail -30"),
    "a swap limit in a background build": (
        "cd /srv/rel/work/fe && (nohup docker run --rm --name fe-build --memory 2500m --memory-swap 4g "
        "-e NEXT_TELEMETRY_DISABLED=1 -w /app -v /srv/rel/work/fe/src:/app "
        "-v /srv/rel/work/nm/node_modules:/app/node_modules:ro node:20-alpine sh -c \"npx next build\" "
        "> /srv/rel/work/fe/build.log 2>&1 &); sleep 45; tail -5 /srv/rel/work/fe/build.log"),
}


@pytest.mark.parametrize("shape", sorted(RECORDED))
def test_a_recorded_container_run_with_an_unknown_option_passes(shape):
    command = RECORDED[shape]
    assert eb.analyze(command)["verdict"] in eb._TERMINAL_SAFE
    was_refused, err = refused(command)
    assert not was_refused, err


@pytest.mark.parametrize("command", [
    "docker run --dns 1.1.1.1 --rm img ls",
    "docker run --dns=1.1.1.1 --rm img ls",
    "podman run --rm --memory-swap 1g img ls",
    "docker create --rm --sysctl net.ipv4.ip_forward=1 img ls",
    "docker exec --detach-keys ctrl-x --frobnicate box ls -la /rm-me",
    "docker --log-format json run --rm img ls",
    "docker compose --progress plain run --rm web ls",
])
def test_an_unknown_option_of_a_non_removing_container_command_passes(command):
    assert eb.analyze(command)["verdict"] in eb._TERMINAL_SAFE, eb.analyze(command)


# Every reading of the unknown option leaves the container's removal where the rule judges it.
@pytest.mark.parametrize("command", [
    "docker run --rm --dns 1.1.1.1 -v /:/host img rm -rf /host",
    "docker run --rm --dns -v /:/host img rm -rf /host",
    "docker run --oom-kill-disable -v /srv:/h img rm -rf /h",
    "docker run --memory-swap 1g img sh -c 'rm -rf /h'",
    "docker create --dns 1.1.1.1 -v /:/host img rm -rf /host",
    "docker exec --frobnicate x box rm -rf /h",
    "podman run --dns 1.1.1.1 -v /:/host img find /host -delete",
    "docker --log-format json run -v /:/h img rm -rf /h",
    "docker compose --progress plain run web rm -rf /h",
    "docker compose --ansi never run web rm -rf /h",   # --ansi takes a value: `never` is no subcommand
])
def test_a_removal_inside_the_container_stays_refused_under_an_unknown_option(command):
    assert eb.analyze(command)["verdict"] not in eb._TERMINAL_SAFE
    was_refused, _ = refused(command)
    assert was_refused


@pytest.mark.parametrize("command", [
    "docker run -v /:/host img rm -rf /host",
    "docker run --rm -v /:/host img sh -c 'rm -rf /host/x'",
])
def test_a_known_option_container_removal_stays_refused(command):
    was_refused, _ = refused(command)
    assert was_refused


@pytest.mark.parametrize("command", [
    "docker rm -f box", "docker container rm box", "docker rmi img", "docker system prune -a",
    "docker --log-format json rm box",
])
def test_the_container_removal_subcommands_stay_judged_as_docker_resource_removals(command):
    result = eb.analyze(command)
    assert result["verdict"] == eb.PROVEN_SAFE_REMOVAL
    assert any(b.get("reason") == "docker_resource_removal" for b in result["boundaries"])
